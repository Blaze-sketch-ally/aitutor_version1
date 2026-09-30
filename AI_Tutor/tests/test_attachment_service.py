import asyncio
from io import BytesIO

import pytest
from PIL import Image

from schemas.attachment import AttachmentType
from services.attachment_service import (
    AttachmentService,
    AttachmentValidationError,
)


def _make_image_bytes(fmt: str, size=(12, 12), color=(255, 0, 0)) -> bytes:

    img = Image.new("RGB", size, color)
    buf = BytesIO()

    try:
        img.save(buf, format=fmt)
    except (KeyError, OSError) as e:
        pytest.skip(f"Pillow build does not support encoding {fmt}: {e}")

    return buf.getvalue()


class FakeUploadFile:
    """
    Minimal stand-in for fastapi.UploadFile — only the interface
    AttachmentService.process_image_uploads() actually uses
    (async .read(), .filename, .content_type).
    """

    def __init__(self, filename, data, content_type=None):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self):
        return self._data


# ==================================================
# TYPE IDENTIFICATION
# ==================================================

class TestIdentifyAttachmentType:

    def test_pdf_extension(self):
        service = AttachmentService()
        assert service.identify_attachment_type(
            "notes.pdf"
        ) == AttachmentType.PDF

    def test_image_extensions(self):
        service = AttachmentService()
        for name in ("photo.png", "photo.jpg", "photo.jpeg", "photo.webp"):
            assert service.identify_attachment_type(
                name
            ) == AttachmentType.IMAGE

    def test_image_by_content_type_with_unknown_extension(self):
        service = AttachmentService()
        assert service.identify_attachment_type(
            "blob", content_type="image/png"
        ) == AttachmentType.IMAGE

    def test_video_and_txt_are_other_supported(self):
        service = AttachmentService()
        for name in ("lecture.mp4", "clip.mp3", "notes.txt"):
            assert service.identify_attachment_type(
                name
            ) == AttachmentType.OTHER_SUPPORTED_FILE

    def test_executable_is_unsupported(self):
        service = AttachmentService()
        assert service.identify_attachment_type(
            "totally_safe.exe"
        ) == AttachmentType.UNSUPPORTED


# ==================================================
# IMAGE VALIDATION
# ==================================================

class TestValidateImageBytes:

    def test_valid_png(self):
        service = AttachmentService()
        data = _make_image_bytes("PNG")
        info = service.validate_image_bytes(data, "a.png")
        assert info["format"] == "PNG"
        assert info["width"] == 12 and info["height"] == 12

    def test_valid_jpeg(self):
        service = AttachmentService()
        data = _make_image_bytes("JPEG")
        info = service.validate_image_bytes(data, "a.jpg")
        assert info["format"] == "JPEG"

    def test_valid_webp(self):
        service = AttachmentService()
        data = _make_image_bytes("WEBP")
        info = service.validate_image_bytes(data, "a.webp")
        assert info["format"] == "WEBP"

    def test_empty_file_rejected(self):
        service = AttachmentService()
        with pytest.raises(AttachmentValidationError, match="empty"):
            service.validate_image_bytes(b"", "a.png")

    def test_garbage_bytes_rejected(self):
        service = AttachmentService()
        with pytest.raises(AttachmentValidationError, match="Unable to read"):
            service.validate_image_bytes(b"not an image at all", "a.png")

    def test_corrupted_image_rejected(self):
        service = AttachmentService()
        data = _make_image_bytes("PNG")
        truncated = data[: len(data) // 2]
        with pytest.raises(AttachmentValidationError, match="Unable to read"):
            service.validate_image_bytes(truncated, "a.png")

    def test_oversized_image_rejected(self):
        service = AttachmentService()
        service.max_image_size_bytes = 10  # force a tiny cap
        service.max_image_size_mb = 10 / (1024 * 1024)

        data = _make_image_bytes("PNG")
        with pytest.raises(AttachmentValidationError, match="too large"):
            service.validate_image_bytes(data, "a.png")

    def test_unsupported_format_rejected(self):
        service = AttachmentService()
        # BMP is readable by Pillow but not in our supported set.
        img = Image.new("RGB", (5, 5))
        buf = BytesIO()
        img.save(buf, format="BMP")

        with pytest.raises(
            AttachmentValidationError, match="Unsupported image format"
        ):
            service.validate_image_bytes(buf.getvalue(), "a.bmp")

    def test_mime_type_for_maps_known_formats(self):
        service = AttachmentService()
        assert service.mime_type_for("PNG") == "image/png"
        assert service.mime_type_for("JPEG") == "image/jpeg"
        assert service.mime_type_for("WEBP") == "image/webp"
        assert service.mime_type_for("BOGUS") == "image/png"


# ==================================================
# STAGING / PROCESSING
# ==================================================

class TestProcessImageUploads:

    def test_single_image_staged_and_cleaned_up(self):
        service = AttachmentService()
        files = [FakeUploadFile("a.png", _make_image_bytes("PNG"))]

        metadata, temp_paths = asyncio.run(
            service.process_image_uploads(files)
        )

        assert len(metadata) == 1
        assert metadata[0].attachment_type == AttachmentType.IMAGE
        assert metadata[0].filename == "a.png"
        assert len(temp_paths) == 1

        import os
        assert os.path.exists(temp_paths[0])

        service.cleanup_temp_files(temp_paths)
        assert not os.path.exists(temp_paths[0])

    def test_multiple_images_within_limit(self):
        service = AttachmentService()
        files = [
            FakeUploadFile("a.png", _make_image_bytes("PNG")),
            FakeUploadFile("b.jpg", _make_image_bytes("JPEG")),
        ]

        metadata, temp_paths = asyncio.run(
            service.process_image_uploads(files)
        )

        assert len(metadata) == 2
        assert len(temp_paths) == 2

        service.cleanup_temp_files(temp_paths)

    def test_too_many_images_rejected(self):
        service = AttachmentService()
        service.max_images_per_message = 1

        files = [
            FakeUploadFile("a.png", _make_image_bytes("PNG")),
            FakeUploadFile("b.png", _make_image_bytes("PNG")),
        ]

        with pytest.raises(AttachmentValidationError, match="Too many images"):
            asyncio.run(service.process_image_uploads(files))

    def test_invalid_image_in_batch_cleans_up_prior_temp_files(self):
        service = AttachmentService()

        files = [
            FakeUploadFile("a.png", _make_image_bytes("PNG")),
            FakeUploadFile("bad.png", b"garbage"),
        ]

        with pytest.raises(AttachmentValidationError):
            asyncio.run(service.process_image_uploads(files))

        # The first (valid) file's temp path must not be left behind.
        import glob
        leftovers = glob.glob(
            "temp_uploads/images/*a.png"
        )
        assert leftovers == []

    def test_cleanup_ignores_missing_files(self):
        service = AttachmentService()
        # Should not raise even though these paths don't exist.
        service.cleanup_temp_files(["temp_uploads/images/does_not_exist.png"])


# ==================================================
# PDF REFERENCE (image + pdf foundation)
# ==================================================

class TestDescribePdfReference:

    def test_wraps_pdf_name_without_temp_path(self):
        service = AttachmentService()
        meta = service.describe_pdf_reference("operating_systems.pdf")

        assert meta.attachment_type == AttachmentType.PDF
        assert meta.filename == "operating_systems.pdf"
        assert meta.temp_path is None

    def test_mixed_image_and_pdf_list(self):
        service = AttachmentService()
        image_meta, temp_paths = asyncio.run(
            service.process_image_uploads(
                [FakeUploadFile("diagram.png", _make_image_bytes("PNG"))]
            )
        )
        pdf_meta = service.describe_pdf_reference("notes.pdf")

        combined = image_meta + [pdf_meta]
        types = {m.attachment_type for m in combined}

        assert types == {AttachmentType.IMAGE, AttachmentType.PDF}

        service.cleanup_temp_files(temp_paths)
