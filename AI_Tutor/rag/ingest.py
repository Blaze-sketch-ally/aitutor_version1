from pathlib import Path

from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter


from rag.vectorstore import VectorStore


UNREADABLE_PDF_MESSAGE = "Unreadable PDF."


class PDFIngestor:

    def __init__(
        self,
        session_id: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200
    ):

        self.session_id = session_id

        self.vectorstore = VectorStore(
            session_id=session_id
        )

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=[
                "\n\n",
                "\n",
                ". ",
                " ",
                ""
            ]
        )

    # ----------------------------------
    # EXTRACT PAGE-WISE TEXT
    # ----------------------------------

    def extract_pages(
        self,
        pdf_path: str
    ):

        # A corrupt, truncated or password-protected file is the user's
        # file problem, not a server fault: raise one fixed message that
        # api/pdf.py maps to a 4xx (parser internals stay in the log).
        try:
            reader = PdfReader(pdf_path)
            if reader.is_encrypted:
                raise ValueError("encrypted")
            _ = len(reader.pages)
        except Exception as e:
            print(f"Unreadable PDF ({type(e).__name__}): {e}")
            raise ValueError(UNREADABLE_PDF_MESSAGE) from e

        pages = []

        for page_num, page in enumerate(
            reader.pages,
            start=1
        ):

            try:

                text = page.extract_text()

                if text and text.strip():

                    pages.append(
                        {
                            "page": page_num,
                            "text": text
                        }
                    )

            except Exception as e:

                print(
                    f"Page extraction error: {e}"
                )

        return pages

    # ----------------------------------
    # INGEST PDF
    # ----------------------------------

    def ingest_pdf(
        self,
        pdf_path: str,
        pdf_name: str | None = None
    ):
        """
        pdf_name: the user-facing filename to store as `source`.
        Defaults to the file's basename; pass it explicitly when the
        local path is a uniquely-named temp file.
        """

        try:

            pdf_name = pdf_name or Path(
                pdf_path
            ).name

            # One id per upload — see VectorStore.make_chunk_id().
            document_id = self.vectorstore.new_document_id()

            print(
                f"Processing PDF: {pdf_name}"
            )

            # -------------------------
            # Extract Pages
            # -------------------------

            pages = self.extract_pages(
                pdf_path
            )

            if not pages:

                raise ValueError(
                    "No text found in PDF."
                )

            chunks = []
            metadatas = []
            ids = []

            chunk_counter = 0

            # -------------------------
            # Split Page Wise
            # -------------------------

            for page_data in pages:

                page_number = page_data["page"]

                page_text = page_data["text"]

                page_chunks = (
                    self.splitter.split_text(
                        page_text
                    )
                )

                for chunk in page_chunks:

                    chunks.append(chunk)

                    ids.append(
                        self.vectorstore.make_chunk_id(
                            document_id,
                            chunk_counter
                        )
                    )

                    metadatas.append(
                        {
                            "doc_id": document_id,
                            "source": pdf_name,
                            "page": page_number,
                            "chunk_id": chunk_counter,
                            "session_id": self.session_id
                        }
                    )

                    chunk_counter += 1

            if not chunks:

                raise ValueError(
                    "No chunks generated."
                )

            # -------------------------
            # Store in Vector DB
            # -------------------------

            # Raises on embedding/insert failure, which lands in the
            # except below and is reported as status "error".
            self.vectorstore.add_documents(
                chunks=chunks,
                ids=ids,
                metadatas=metadatas,
                document_id=document_id
            )

            print(
                f"Stored {len(chunks)} chunks "
                f"in session {self.session_id}"
            )

            return {
                "status": "success",
                "pdf_name": pdf_name,
                "document_id": document_id,
                "chunks_created": len(chunks),
                "session_id": self.session_id
            }

        except Exception as e:

            print(
                f"PDF Ingestion Error: {e}"
            )

            return {
                "status": "error",
                "message": str(e)
            }