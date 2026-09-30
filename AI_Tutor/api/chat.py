import os
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.jwt_bearer import CurrentUser, get_current_user
from memory.session_manager import SessionOwnershipError
from models.errors import ServiceUnavailableError
from services.chat_api_service import ChatAPIService
from services.attachment_service import AttachmentService, AttachmentValidationError

VIDEO_TEMP_DIR = "temp_uploads"

GENERIC_ERROR = "Something went wrong while handling this request. Please try again."


router = APIRouter(prefix="/api/chat", tags=["chat"])

chat_api_service = ChatAPIService()
attachment_service = AttachmentService()


class ChatRequest(BaseModel):
    session_id: str
    query: str
    selected_pdfs: list[str] = []


class StopChatRequest(BaseModel):
    session_id: str
    query: str
    selected_pdfs: list[str] = []
    mode: str
    partial_text: str
    sources: list = []


@router.post("/")
def chat(
    req: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    try:
        result = chat_api_service.run(
            user_id=current_user.id,
            session_id=req.session_id,
            query=req.query,
            selected_pdfs=req.selected_pdfs
        )
    except (SessionOwnershipError, ServiceUnavailableError):
        # Let main.py's exception handlers turn these into a 404 / 503 —
        # don't let the blanket Exception catch below mask them as a 500.
        raise
    except Exception as e:
        # Log the real cause; never echo internals (DB/provider text)
        # to the client.
        print(f"Chat request failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)

    return result


@router.post("/stream")
def chat_stream(
    req: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Server-Sent-Events counterpart to POST /api/chat/ for plain-text
    turns (no image/video attachment — those keep going through the
    existing /images and /video routes above, unchanged and non-
    streamed). See ChatAPIService.stream() for the frame format and for
    how this reuses Orchestrator.run_stream() + the existing
    _persist_turn() persistence path.
    """
    return StreamingResponse(
        chat_api_service.stream(
            user_id=current_user.id,
            session_id=req.session_id,
            query=req.query,
            selected_pdfs=req.selected_pdfs
        ),
        media_type="text/event-stream"
    )


@router.post("/stream/stop")
def chat_stream_stop(
    req: StopChatRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Called by the frontend right after it aborts an in-progress
    /api/chat/stream fetch (Stop button). The client already has
    whatever text streamed in before it aborted — this just persists
    that partial text through the same save path a completed turn
    uses, tagged stopped=True, via ChatAPIService.persist_partial().
    """
    try:
        chat_api_service.persist_partial(
            user_id=current_user.id,
            session_id=req.session_id,
            query=req.query,
            selected_pdfs=req.selected_pdfs,
            mode=req.mode,
            partial_text=req.partial_text,
            sources=req.sources
        )
    except (SessionOwnershipError, ServiceUnavailableError):
        # Let main.py's exception handlers turn these into a 404 / 503 —
        # don't let the blanket Exception catch below mask them as a 500.
        raise
    except Exception as e:
        # Log the real cause; never echo internals (DB/provider text)
        # to the client.
        print(f"Chat request failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)

    return {"success": True}


@router.post("/video")
async def chat_with_video(
    session_id: str = Form(...),
    query: str = Form(""),
    selected_pdfs: str = Form("[]"),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Multipart counterpart to POST /api/chat/ — for the paperclip
    attach-a-video case in app_new.py's chat_input. Plain YouTube
    links need none of this: they're just text in `query` on the
    normal JSON endpoint, since Orchestrator.run() already detects
    a YouTube URL inside the query string on its own.

    `selected_pdfs` arrives as a JSON-encoded string (not a native
    list) because multipart/form-data fields are always strings —
    the frontend should send e.g. selected_pdfs='["a.pdf","b.pdf"]'.
    """

    try:
        parsed_pdfs = json.loads(selected_pdfs)
    except (json.JSONDecodeError, TypeError):
        parsed_pdfs = []

    os.makedirs(VIDEO_TEMP_DIR, exist_ok=True)

    # uuid-prefixed filename avoids collisions between concurrent
    # uploads across different users/sessions sharing this temp dir —
    # app_new.py doesn't need this since Streamlit handles one user's
    # script run at a time, but a shared FastAPI process can interleave
    # requests.
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    temp_path = os.path.join(VIDEO_TEMP_DIR, safe_name)

    video_bytes = await file.read()

    with open(temp_path, "wb") as f:
        f.write(video_bytes)

    effective_query = query.strip() or f"Summarize this uploaded video: {file.filename}"

    try:
        result = chat_api_service.run(
            user_id=current_user.id,
            session_id=session_id,
            query=effective_query,
            selected_pdfs=parsed_pdfs,
            uploaded_video_path=temp_path
        )
    except (SessionOwnershipError, ServiceUnavailableError):
        # Let main.py's exception handlers turn these into a 404 / 503 —
        # don't let the blanket Exception catch below mask them as a 500.
        raise
    except Exception as e:
        # Log the real cause; never echo internals (DB/provider text)
        # to the client.
        print(f"Chat request failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)
    finally:
        # VideoSummaryAgent only cleans up its own temp dir for
        # YouTube downloads — an uploaded file is owned by this route,
        # same division of responsibility as app_new.py.
        try:
            os.remove(temp_path)
        except OSError:
            pass

    return result


@router.post("/images")
async def chat_with_images(
    session_id: str = Form(...),
    query: str = Form(""),
    selected_pdfs: str = Form("[]"),
    files: list[UploadFile] = File(...),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Multipart counterpart to POST /api/chat/ for image attachments —
    same shape/spirit as /video above, but supports MULTIPLE files
    (field name is plural "files", unlike /video and /pdf/upload's
    singular "file") and routes them through VisionAgent (via
    Orchestrator.run(image_attachments=...)) instead of
    VideoSummaryAgent.

    Images are never persisted or indexed — no Supabase Storage, no
    rag/ingest.py involvement. AttachmentService validates and stages
    them as ephemeral temp files (same uuid-prefixed temp_uploads/
    pattern /video uses for its own file), and this route deletes them
    in `finally` regardless of outcome, mirroring /video's cleanup.
    """

    try:
        parsed_pdfs = json.loads(selected_pdfs)
    except (json.JSONDecodeError, TypeError):
        parsed_pdfs = []

    temp_paths = []

    try:
        metadata_list, temp_paths = await attachment_service.process_image_uploads(
            files
        )
    except AttachmentValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    image_attachments = [
        {
            "path": meta.temp_path,
            "mime_type": meta.mime_type,
            "filename": meta.filename
        }
        for meta in metadata_list
    ]

    default_query = (
        "Explain this image." if len(image_attachments) == 1
        else "Explain these images."
    )
    effective_query = query.strip() or default_query

    try:
        result = chat_api_service.run(
            user_id=current_user.id,
            session_id=session_id,
            query=effective_query,
            selected_pdfs=parsed_pdfs,
            image_attachments=image_attachments
        )
    except (SessionOwnershipError, ServiceUnavailableError):
        # Let main.py's exception handlers turn these into a 404 / 503 —
        # don't let the blanket Exception catch below mask them as a 500.
        raise
    except Exception as e:
        # Log the real cause; never echo internals (DB/provider text)
        # to the client.
        print(f"Chat request failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=GENERIC_ERROR)
    finally:
        attachment_service.cleanup_temp_files(temp_paths)

    return result


# ==========================================================
# NOTE: /video and /images above intentionally stay non-streamed —
# Orchestrator.run_stream() only supports plain-text turns (no
# image_attachments param). POST /stream above is the token-by-token
# path, used by the frontend for text-only sends; attachments keep
# going through the request/response routes here unchanged.
# ==========================================================
