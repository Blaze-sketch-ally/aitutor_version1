import os
import tempfile

from unittest.mock import MagicMock, patch

import agents.orchestrator as orchestrator_module


def _make_orchestrator_with_mocks():
    """
    Orchestrator.__init__ constructs Retriever/ChatMemory/SessionManager,
    all of which talk to Supabase for real. Patching them at their
    point of use inside agents.orchestrator (not at their own module)
    is the standard way to keep these tests fast/offline without
    touching the real orchestrator wiring logic under test.
    """

    with patch.object(orchestrator_module, "Retriever") as MockRetriever, \
         patch.object(orchestrator_module, "ChatMemory") as MockChatMemory, \
         patch.object(orchestrator_module, "SessionManager") as MockSessionManager, \
         patch.object(orchestrator_module, "YouTubeAgent"), \
         patch.object(orchestrator_module, "VideoSummaryAgent"):
        # YouTubeAgent/VideoSummaryAgent are mocked defensively even
        # though these tests never route to them: YouTubeAgent's
        # constructor builds a googleapiclient discovery client, which
        # can attempt a real network call at construction time
        # depending on the installed client version. Every test that
        # builds an Orchestrator pays that cost otherwise.

        MockRetriever.return_value.has_documents.return_value = False
        MockChatMemory.return_value.get_history_text.return_value = ""
        MockChatMemory.return_value.size.return_value = 1
        MockSessionManager.return_value.session_exists.return_value = True

        orch = orchestrator_module.Orchestrator(
            user_id="testuser",
            session_id="test-session"
        )

    return orch


def _intents(**overrides):

    base = {
        "chat": False, "answer": False, "quiz": False, "notes": False,
        "diagram": False, "videos": False, "papers": False,
        "comparison": False, "all_pdfs": False, "web_research": False,
        "external_action": False, "knowledge_source": "general",
        "resource_source": "query"
    }

    base.update(overrides)

    return base


class TestIntentRouting:

    def test_normal_tutor_query_calls_tutor_agent(self):

        orch = _make_orchestrator_with_mocks()

        orch.intent_classifier.classify = MagicMock(
            return_value=_intents(answer=True)
        )
        orch.summary_agent.summarize = MagicMock(return_value="")
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "explain gradient descent"}
        )
        orch.tutor.generate_answer = MagicMock(
            return_value="Gradient descent is..."
        )
        orch.web_research.research = MagicMock()
        orch.task_router.route_task = MagicMock()

        result = orch.run("explain gradient descent")

        orch.tutor.generate_answer.assert_called()
        orch.web_research.research.assert_not_called()
        orch.task_router.route_task.assert_not_called()
        assert result["answer"] == "Gradient descent is..."

    def test_pdf_query_uses_retrieved_context(self):

        orch = _make_orchestrator_with_mocks()

        orch.retriever.has_documents = MagicMock(return_value=True)
        orch.retriever.get_context_with_sources = MagicMock(return_value={
            "context": "PDF content about neural networks...",
            "sources": [{"source": "notes.pdf", "page": 1, "chunk_id": "notes.pdf_chunk_0"}]
        })

        orch.intent_classifier.classify = MagicMock(
            return_value=_intents(answer=True, knowledge_source="pdf", resource_source="pdf")
        )
        orch.summary_agent.summarize = MagicMock(return_value="")
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "summarize the pdf"}
        )
        orch.tutor.generate_answer = MagicMock(
            return_value="Summary based on PDF..."
        )

        result = orch.run("summarize the pdf", selected_pdfs=["notes.pdf"])

        _, kwargs = orch.tutor.generate_answer.call_args
        assert "neural networks" in kwargs["context"]
        assert result["answer"] == "Summary based on PDF..."

    def test_web_research_query_calls_web_research_not_task_router(self):

        orch = _make_orchestrator_with_mocks()

        orch.intent_classifier.classify = MagicMock(
            return_value=_intents(web_research=True)
        )
        orch.summary_agent.summarize = MagicMock(return_value="")
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "latest ai news"}
        )
        orch.web_research.research = MagicMock(
            return_value={"answer": "Here's the latest...", "results": []}
        )
        orch.task_router.route_task = MagicMock()

        result = orch.run("what's the latest ai news")

        orch.web_research.research.assert_called_once()
        orch.task_router.route_task.assert_not_called()
        assert result["web_research"] == "Here's the latest..."

    def test_external_action_query_calls_task_router_not_web_research(self):

        orch = _make_orchestrator_with_mocks()

        orch.intent_classifier.classify = MagicMock(
            return_value=_intents(external_action=True)
        )
        orch.summary_agent.summarize = MagicMock(return_value="")
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "where can I apply for a passport"}
        )
        orch.task_router.route_task = MagicMock(return_value={
            "message": "You can apply on the official government portal.",
            "action": {
                "label": "Open Official Portal",
                "url": "https://example.gov",
                "service": "Government Portal",
                "source_type": "official"
            }
        })
        orch.web_research.research = MagicMock()

        result = orch.run("where can I apply for a passport")

        orch.task_router.route_task.assert_called_once()
        orch.web_research.research.assert_not_called()
        assert result["external_action"]["action"]["url"] == "https://example.gov"

    def test_external_action_no_result_gets_graceful_notice_not_crash(self):

        orch = _make_orchestrator_with_mocks()

        orch.intent_classifier.classify = MagicMock(
            return_value=_intents(external_action=True)
        )
        orch.summary_agent.summarize = MagicMock(return_value="")
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "where can I do the obscure thing"}
        )
        orch.task_router.route_task = MagicMock(
            return_value={"message": None, "action": None}
        )
        orch.tutor.generate_answer = MagicMock(return_value="")

        result = orch.run("where can I do the obscure thing")

        assert "external_action" not in result
        assert "verified official source" in result["answer"]


class TestImageAttachmentRouting:

    def test_image_attachment_merges_into_context_and_calls_tutor(self):

        orch = _make_orchestrator_with_mocks()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake-image-bytes")
            temp_path = f.name

        try:
            orch.intent_classifier.classify = MagicMock(
                return_value=_intents(answer=True)
            )
            orch.summary_agent.summarize = MagicMock(return_value="")
            orch.query_resolver.resolve = MagicMock(
                return_value={"resolved_query": "explain this image"}
            )
            orch.vision.analyze_images = MagicMock(return_value={
                "description": "A diagram of CPU scheduling algorithms.",
                "detected_text": "FCFS, SJF, Round Robin",
                "confidence": 0.8,
            })
            orch.tutor.generate_answer = MagicMock(
                return_value="This diagram shows..."
            )

            result = orch.run(
                "explain this image",
                image_attachments=[{
                    "path": temp_path,
                    "mime_type": "image/png",
                    "filename": "diagram.png"
                }]
            )

            orch.vision.analyze_images.assert_called_once()

            _, kwargs = orch.tutor.generate_answer.call_args
            assert "CPU scheduling" in kwargs["context"]
            assert "FCFS, SJF, Round Robin" in kwargs["context"]
            assert result["answer"] == "This diagram shows..."

        finally:
            os.remove(temp_path)

    def test_no_image_attachments_does_not_call_vision_agent(self):

        orch = _make_orchestrator_with_mocks()

        orch.intent_classifier.classify = MagicMock(
            return_value=_intents(answer=True)
        )
        orch.summary_agent.summarize = MagicMock(return_value="")
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "explain gradient descent"}
        )
        orch.vision.analyze_images = MagicMock()
        orch.tutor.generate_answer = MagicMock(return_value="...")

        orch.run("explain gradient descent")

        orch.vision.analyze_images.assert_not_called()

    def test_image_plus_pdf_merges_both_into_cross_pdf_contexts(self):

        orch = _make_orchestrator_with_mocks()

        orch.retriever.has_documents = MagicMock(return_value=True)
        orch.retriever.get_grouped_context_by_source = MagicMock(return_value={
            "pdf_contexts": {"notes.pdf": "PDF content about circuits..."},
            "sources": []
        })

        orch.intent_classifier.classify = MagicMock(
            return_value=_intents(
                comparison=True, knowledge_source="hybrid"
            )
        )
        orch.summary_agent.summarize = MagicMock(return_value="")
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "compare this image with my pdf"}
        )
        orch.vision.analyze_images = MagicMock(return_value={
            "description": "A hand-drawn circuit diagram.",
        })
        orch.comparison.generate_comparison = MagicMock(
            return_value="Comparison result..."
        )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake-bytes")
            temp_path = f.name

        try:
            result = orch.run(
                "compare this image with my pdf",
                selected_pdfs=["notes.pdf"],
                image_attachments=[{
                    "path": temp_path,
                    "mime_type": "image/png",
                    "filename": "circuit.png"
                }]
            )

            _, kwargs = orch.comparison.generate_comparison.call_args
            assert "Attached Image(s)" in kwargs["pdf_contexts"]
            assert "circuit diagram" in kwargs["pdf_contexts"]["Attached Image(s)"]
            assert result["comparison"] == "Comparison result..."

        finally:
            os.remove(temp_path)

    def test_unreadable_image_path_does_not_crash(self):

        orch = _make_orchestrator_with_mocks()

        orch.intent_classifier.classify = MagicMock(
            return_value=_intents(answer=True)
        )
        orch.summary_agent.summarize = MagicMock(return_value="")
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "explain this"}
        )
        orch.vision.analyze_images = MagicMock()
        orch.tutor.generate_answer = MagicMock(return_value="fallback answer")

        result = orch.run(
            "explain this",
            image_attachments=[{
                "path": "/nonexistent/path.png",
                "mime_type": "image/png",
                "filename": "x.png"
            }]
        )

        orch.vision.analyze_images.assert_not_called()
        assert result["answer"] == "fallback answer"
