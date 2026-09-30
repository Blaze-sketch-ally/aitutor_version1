import os
import uuid
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from schemas.attachment import AttachmentMetadata, AttachmentType

# ==================================================
# CONFIG
# ==================================================

# Pillow's own detected format is what's trusted — never the filename
# extension or the client-supplied content-type alone.
SUPPORTED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/webp"
}

FORMAT_TO_MIME_TYPE = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}

PDF_EXTENSION = ".pdf"

# "Upload files" scope agreed for this step's foundation: video/audio
# reuse the existing /api/chat/video pipeline untouched (this module
# never processes them), plus a plain .txt read (no OCR/RAG). Nothing
# else is accepted as OTHER_SUPPORTED_FILE.
OTHER_SUPPORTED_EXTENSIONS = {
    ".txt",
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4a", ".mp3", ".wav",
}

IMAGE_TEMP_DIR = os.path.join("temp_uploads", "images")


class AttachmentValidationError(Exception):
    """Raised for any user-facing attachment validation failure."""


class AttachmentService:
    """
    Reusable attachment processing layer for the new multimodal
    system. Handles ONLY image validation/staging and attachment-type
    identification — it deliberately does not duplicate any part of
    the existing PDF/RAG pipeline (rag/ingest.py, rag/vectorstore.py)
    or the existing video attachment flow (api/chat.py's /video
    route); PDFs and videos keep going through exactly those, and this
    service only recognizes/represents them via
    identify_attachment_type() / describe_pdf_reference().
    """

    def __init__(self):
        self.max_image_size_mb = float(
            os.getenv("MAX_IMAGE_SIZE_MB", "8")
        )
        self.max_image_size_bytes = int(
            self.max_image_size_mb * 1024 * 1024
        )

        # Matches Groq's actual per-request image limit for the
        # configured vision model (see models/vision_client.py) — not
        # an arbitrary cap. Adjust via env if the configured model
        # changes its limit.
        self.max_images_per_message = int(
            os.getenv("MAX_IMAGES_PER_MESSAGE", "5")
        )

    # ==================================================
    # TYPE IDENTIFICATION
    # ==================================================

    def identify_attachment_type(
        self,
        filename: str,
        content_type: str | None = None
    ) -> AttachmentType:

        ext = os.path.splitext(filename or "")[1].lower()

        if ext == PDF_EXTENSION:
            return AttachmentType.PDF

        if ext in SUPPORTED_IMAGE_EXTENSIONS:
            return AttachmentType.IMAGE

        if content_type in SUPPORTED_IMAGE_MIME_TYPES:
            return AttachmentType.IMAGE

        if ext in OTHER_SUPPORTED_EXTENSIONS:
            return AttachmentType.OTHER_SUPPORTED_FILE

        return AttachmentType.UNSUPPORTED

    # ==================================================
    # IMAGE VALIDATION
    # ==================================================

    def validate_image_bytes(self, data: bytes, filename: str) -> dict:
        """
        Validates image bytes without trusting the filename/extension
        or the client-supplied content-type — the actual bytes are
        decoded with Pillow, which is what determines the real format.

        Returns {"format", "width", "height", "size_bytes"} on
        success, or raises AttachmentValidationError with a
        user-facing message on failure.
        """

        if not data:
            raise AttachmentValidationError("Image file is empty.")

        if len(data) > self.max_image_size_bytes:
            raise AttachmentValidationError(
                f"Image is too large. Maximum allowed size is "
                f"{self.max_image_size_mb:.0f}MB."
            )

        try:
            probe = Image.open(BytesIO(data))
            probe.verify()
        except (UnidentifiedImageError, OSError, ValueError):
            raise AttachmentValidationError("Unable to read image.")

        # .verify() invalidates the Image object for further use, so
        # a fresh Image is opened from the same bytes to safely read
        # format/dimensions.
        try:
            img = Image.open(BytesIO(data))
            image_format = img.format
            width, height = img.size
        except (UnidentifiedImageError, OSError, ValueError):
            raise AttachmentValidationError("Unable to read image.")

        if image_format not in SUPPORTED_IMAGE_FORMATS:
            raise AttachmentValidationError("Unsupported image format.")

        return {
            "format": image_format,
            "width": width,
            "height": height,
            "size_bytes": len(data),
        }

    def mime_type_for(self, image_format: str | None) -> str:
        return FORMAT_TO_MIME_TYPE.get(
            (image_format or "").upper(), "image/png"
        )

    # ==================================================
    # STAGING (ephemeral — same pattern as the existing video
    # attachment flow in api/chat.py)
    # ==================================================

    async def process_image_uploads(self, files: list) -> tuple:
        """
        Validates and stages uploaded images as temp files.

        `files` is a list of FastAPI UploadFile objects (typed loosely
        here to avoid importing fastapi into a module that also has
        pure-unit-testable logic — the async .read()/.filename/
        .content_type interface is all that's required).

        Never touches Supabase Storage or rag/ingest.py — images are
        not persisted or indexed, only processed for a single request.

        Returns (metadata_list, temp_paths). temp_paths is returned
        separately so a caller can clean up all staged files in one
        `finally` block regardless of what happens to the metadata
        objects afterward.
        """

        if len(files) > self.max_images_per_message:
            raise AttachmentValidationError(
                f"Too many images. Maximum "
                f"{self.max_images_per_message} images per message."
            )

        os.makedirs(IMAGE_TEMP_DIR, exist_ok=True)

        metadata_list: list[AttachmentMetadata] = []
        temp_paths: list[str] = []

        try:
            for file in files:
                data = await file.read()

                info = self.validate_image_bytes(
                    data, file.filename or "image"
                )

                safe_name = os.path.basename(file.filename or "image")
                temp_path = os.path.join(
                    IMAGE_TEMP_DIR, f"{uuid.uuid4().hex}_{safe_name}"
                )

                with open(temp_path, "wb") as f:
                    f.write(data)

                temp_paths.append(temp_path)

                metadata_list.append(
                    AttachmentMetadata(
                        attachment_type=AttachmentType.IMAGE,
                        filename=file.filename or "image",
                        mime_type=self.mime_type_for(info["format"]),
                        size_bytes=info["size_bytes"],
                        temp_path=temp_path,
                        width=info["width"],
                        height=info["height"],
                        format=info["format"],
                    )
                )

            return metadata_list, temp_paths

        except Exception:
            self.cleanup_temp_files(temp_paths)
            raise

    def describe_pdf_reference(self, pdf_name: str) -> AttachmentMetadata:
        """
        Wraps an already-uploaded/indexed PDF filename (from the
        existing /api/pdf/upload + rag/ingest.py pipeline) into the
        same AttachmentMetadata shape as images, so a combined
        attachment list can represent IMAGE + PDF together — without
        this service touching PDF processing at all. No temp_path:
        the PDF's content already lives in document_chunks via the
        existing RAG pipeline.
        """

        return AttachmentMetadata(
            attachment_type=AttachmentType.PDF,
            filename=pdf_name,
        )

    def cleanup_temp_files(self, paths: list[str]) -> None:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                pass
