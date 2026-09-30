from unittest.mock import MagicMock, patch

import services.chat_api_service as chat_api_service_module
from services.chat_api_service import ChatAPIService


def _service_with_mocked_session():
    service = ChatAPIService()
    service.session_service = MagicMock()
    service.session_service.get_history.return_value = []
    return service


class TestPersistTurnAttachmentPrefixes:

    def test_video_attachment_prefix_unchanged(self):

        service = _service_with_mocked_session()

        service._persist_turn(
            user_id="u", session_id="s", query="summarize this",
            selected_pdfs=[],
            uploaded_video_path="temp_uploads/abc123_lecture.mp4",
            result={"answer": "Here's the summary."}
        )

        messages = service.session_service.save_history.call_args.kwargs["messages"]
        assert messages[0]["content"] == "📎 abc123_lecture.mp4\n\nsummarize this"

    def test_single_image_attachment_prefix(self):

        service = _service_with_mocked_session()

        service._persist_turn(
            user_id="u", session_id="s", query="explain this",
            selected_pdfs=[], uploaded_video_path=None,
            result={"answer": "It's a diagram."},
            image_attachments=[{"filename": "diagram.png", "path": "x"}]
        )

        messages = service.session_service.save_history.call_args.kwargs["messages"]
        assert messages[0]["content"] == "🖼️ diagram.png\n\nexplain this"

    def test_multiple_image_attachments_prefix(self):

        service = _service_with_mocked_session()

        service._persist_turn(
            user_id="u", session_id="s", query="compare these",
            selected_pdfs=[], uploaded_video_path=None,
            result={"answer": "..."},
            image_attachments=[{"filename": "a.png"}, {"filename": "b.png"}]
        )

        messages = service.session_service.save_history.call_args.kwargs["messages"]
        assert messages[0]["content"] == "🖼️ a.png\n🖼️ b.png\n\ncompare these"

    def test_image_only_no_text(self):

        service = _service_with_mocked_session()

        service._persist_turn(
            user_id="u", session_id="s", query="",
            selected_pdfs=[], uploaded_video_path=None,
            result={"answer": "..."},
            image_attachments=[{"filename": "a.png"}]
        )

        messages = service.session_service.save_history.call_args.kwargs["messages"]
        assert messages[0]["content"] == "🖼️ a.png"

    def test_no_attachments_unchanged(self):

        service = _service_with_mocked_session()

        service._persist_turn(
            user_id="u", session_id="s", query="plain text query",
            selected_pdfs=[], uploaded_video_path=None,
            result={"answer": "..."}
        )

        messages = service.session_service.save_history.call_args.kwargs["messages"]
        assert messages[0]["content"] == "plain text query"


class TestRunThreadsImageAttachments:

    def test_run_passes_image_attachments_through(self):

        with patch.object(chat_api_service_module, "load_orchestrator"), \
             patch.object(chat_api_service_module, "ChatService") as MockChatService:

            MockChatService.return_value.run_chat.return_value = {"answer": "ok"}

            service = ChatAPIService()
            service.session_service = MagicMock()
            service.session_service.get_history.return_value = []

            image_attachments = [
                {"path": "p", "mime_type": "image/png", "filename": "a.png"}
            ]

            service.run(
                user_id="u", session_id="s", query="explain this",
                selected_pdfs=[], image_attachments=image_attachments
            )

            _, kwargs = MockChatService.return_value.run_chat.call_args
            assert kwargs["image_attachments"] == image_attachments
