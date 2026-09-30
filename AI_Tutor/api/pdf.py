import os

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException

from auth.jwt_bearer import CurrentUser, get_current_user
from memory.session_manager import SessionManager
from services.session_service import SessionService
from storage.storage_manager import StorageManager
from rag.ingest import PDFIngestor


router = APIRouter(prefix="/api/pdf", tags=["pdf"])

session_service = SessionService()
storage = StorageManager()

# rag/ingest.py messages that describe the PDF itself (safe and useful
# to show); anything else is an internal failure.
USER_FACING_INGEST_ERRORS = {
    "No text found in PDF.": (
        "No extractable text was found in this PDF. Scanned/image-only "
        "PDFs aren't supported yet."
    ),
    "No chunks generated.": "No usable text could be extracted from this PDF.",
    "Unreadable PDF.": (
        "This file couldn't be read as a PDF. It may be corrupted or "
        "password-protected."
    ),
}


@router.post("/upload")
async def upload_pdf(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # =====================================
    # 0. OWNERSHIP CHECK — before any storage/ingestion work
    # =====================================
    # Without this, a request naming another user's session_id would
    # write into their Supabase Storage path and vector rows before
    # anything downstream had a chance to reject it. Uses SessionManager
    # directly (not chat_api_service) since this route touches storage/
    # ingestion outside the Orchestrator entirely.

    session_manager = SessionManager(user_id=current_user.id)

    if not session_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Whether this filename is already recorded on the session decides
    # what a failed upload may clean up below: a brand-new PDF's storage
    # object can be removed, but a re-upload's must not be (the session
    # still lists it and its previous chunks are kept intact).
    already_recorded = any(
        pdf.get("name") == file.filename
        for pdf in (session_manager.get_pdfs(session_id) or [])
    )

    pdf_bytes = await file.read()

    # =====================================
    # 1. UPLOAD TO SUPABASE STORAGE
    # =====================================

    upload_result = storage.upload_pdf(
        session_id=session_id,
        pdf_name=file.filename,
        pdf_bytes=pdf_bytes
    )

    if not upload_result["success"]:
        raise HTTPException(status_code=500, detail=upload_result["message"])

    storage_path = upload_result["storage_path"]

    # =====================================
    # 2. DOWNLOAD TO A TEMP PATH FOR INGESTION
    # =====================================
    # PDFIngestor reads from a local file path, not raw bytes, so this
    # round-trips through storage — same as app_new.py does. Slightly
    # redundant (we already have pdf_bytes in memory) but keeps the
    # ingestion code path identical to the working Streamlit version.

    download_result = storage.download_pdf(storage_path)

    if not download_result["success"]:
        raise HTTPException(status_code=500, detail=download_result["message"])

    temp_path = download_result["temp_path"]

    # =====================================
    # 3. INGEST / CHUNK
    # =====================================

    # Success requires extraction AND embedding AND vector insertion —
    # PDFIngestor reports status "error" if any of them failed (the
    # vector store no longer swallows insert errors).
    ingestor = None

    try:
        ingestor = PDFIngestor(session_id=session_id)
        ingest_result = ingestor.ingest_pdf(
            temp_path,
            pdf_name=file.filename
        )
    except Exception as e:
        ingest_result = {"status": "error", "message": str(e)}
    finally:
        try:
            os.remove(temp_path)
            os.rmdir(os.path.dirname(temp_path))
        except OSError:
            pass

    if ingest_result.get("status") != "success":
        print(
            f"PDF upload failed during ingestion "
            f"(session={session_id}, pdf={file.filename}): "
            f"{ingest_result.get('message')}"
        )
        if not already_recorded:
            storage.delete_pdf(storage_path)
        # Only content problems the user can act on are echoed back;
        # database/embedding errors stay in the server log.
        message = ingest_result.get("message", "")
        if message in USER_FACING_INGEST_ERRORS:
            raise HTTPException(
                status_code=422,
                detail=USER_FACING_INGEST_ERRORS[message]
            )
        raise HTTPException(
            status_code=500,
            detail="PDF ingestion failed. Please try uploading again."
        )

    # =====================================
    # 4. RECORD THE PDF ON THE SESSION
    # =====================================

    try:
        session_service.add_pdf(
            user_id=current_user.id,
            session_id=session_id,
            pdf_name=file.filename,
            pdf_path=storage_path
        )
    except Exception as e:
        print(
            f"PDF upload failed recording metadata "
            f"(session={session_id}, pdf={file.filename}): {e}"
        )
        # Don't leave searchable chunks/storage for a PDF the session
        # doesn't list. Only for a brand-new PDF — on a re-upload the
        # new chunks have already replaced the old ones and are the
        # only copy left.
        if not already_recorded:
            ingestor.vectorstore.delete_document(
                ingest_result["document_id"]
            )
            storage.delete_pdf(storage_path)
        raise HTTPException(
            status_code=500,
            detail="PDF was processed but could not be saved to the session."
        )

    return {
        "success": True,
        "pdf_name": file.filename,
        "storage_path": storage_path,
        "chunks_created": ingest_result.get("chunks_created")
    }


# ==========================================================
# NOT YET HANDLED: uploaded video attachment (the paperclip in
# app_new.py's chat_input). That's a different flow entirely —
# it goes straight into Orchestrator.run(uploaded_video_path=...),
# never touches storage/ingestion — so it belongs on api/chat.py
# as a multipart variant, not here. Flagged in api/chat.py already.
# ==========================================================
