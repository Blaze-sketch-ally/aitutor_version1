import glob
import io
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import api.chat as chat_api_module
from auth.jwt_bearer import CurrentUser, get_current_user
from main import app

# These tests exercise the live route registration/wiring, not JWT
# verification itself (that's auth/jwt_bearer.py's own concern) — so
# the dependency is overridden with a fixed identity rather than every
# test needing to mint a real Supabase JWT.
app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="test-user-id")

client = TestClient(app)


def _png_bytes():
    img = Image.new("RGB", (8, 8), (0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestChatImagesEndpoint:

    def test_valid_image_returns_chat_result(self):

        with patch.object(
            chat_api_module.chat_api_service, "run",
            return_value={"mode": "mixed", "answer": "It's a diagram.", "sources": []}
        ) as mock_run:

            response = client.post(
                "/api/chat/images",
                data={"session_id": "s", "query": "Explain this."},
                files={"files": ("diagram.png", _png_bytes(), "image/png")}
            )

        assert response.status_code == 200
        assert response.json()["answer"] == "It's a diagram."

        _, kwargs = mock_run.call_args
        assert kwargs["query"] == "Explain this."
        assert len(kwargs["image_attachments"]) == 1
        assert kwargs["image_attachments"][0]["filename"] == "diagram.png"
        assert kwargs["image_attachments"][0]["mime_type"] == "image/png"

    def test_blank_query_defaults_to_explain_this_image(self):

        with patch.object(
            chat_api_module.chat_api_service, "run",
            return_value={"answer": "...", "sources": []}
        ) as mock_run:

            client.post(
                "/api/chat/images",
                data={"session_id": "s"},
                files={"files": ("a.png", _png_bytes(), "image/png")}
            )

        _, kwargs = mock_run.call_args
        assert kwargs["query"] == "Explain this image."

    def test_multiple_images_default_query_is_plural(self):

        with patch.object(
            chat_api_module.chat_api_service, "run",
            return_value={"answer": "...", "sources": []}
        ) as mock_run:

            client.post(
                "/api/chat/images",
                data={"session_id": "s"},
                files=[
                    ("files", ("a.png", _png_bytes(), "image/png")),
                    ("files", ("b.png", _png_bytes(), "image/png")),
                ]
            )

        _, kwargs = mock_run.call_args
        assert kwargs["query"] == "Explain these images."
        assert len(kwargs["image_attachments"]) == 2

    def test_invalid_image_returns_400(self):

        response = client.post(
            "/api/chat/images",
            data={"session_id": "s"},
            files={"files": ("bad.png", b"not an image", "image/png")}
        )

        assert response.status_code == 400
        assert "Unable to read image" in response.json()["detail"]

    def test_selected_pdfs_parsed_and_passed_through(self):

        with patch.object(
            chat_api_module.chat_api_service, "run",
            return_value={"answer": "...", "sources": []}
        ) as mock_run:

            client.post(
                "/api/chat/images",
                data={
                    "session_id": "s",
                    "selected_pdfs": '["notes.pdf"]'
                },
                files={"files": ("a.png", _png_bytes(), "image/png")}
            )

        _, kwargs = mock_run.call_args
        assert kwargs["selected_pdfs"] == ["notes.pdf"]

    def test_temp_files_cleaned_up_after_request(self):

        with patch.object(
            chat_api_module.chat_api_service, "run",
            return_value={"answer": "...", "sources": []}
        ):
            client.post(
                "/api/chat/images",
                data={"session_id": "s"},
                files={"files": ("cleanup_check.png", _png_bytes(), "image/png")}
            )

        leftovers = glob.glob("temp_uploads/images/*cleanup_check.png")
        assert leftovers == []

    def test_backend_error_returns_500_not_raw_traceback(self):

        with patch.object(
            chat_api_module.chat_api_service, "run",
            side_effect=RuntimeError("orchestrator exploded")
        ):
            response = client.post(
                "/api/chat/images",
                data={"session_id": "s"},
                files={"files": ("a.png", _png_bytes(), "image/png")}
            )

        assert response.status_code == 500
