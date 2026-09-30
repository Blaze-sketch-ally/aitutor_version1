import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from agents.diagram_agent import extract_explicit_values
from agents.intent_classifier import IntentClassifier
from rag.ingest import UNREADABLE_PDF_MESSAGE, PDFIngestor

from tests.test_orchestrator_routing import _intents
from tests.test_pdf_retrieval_routing import _orch_with


# =====================================================
# PRIORITY 3 — image understanding vs. image generation
# =====================================================

class TestVisionRouting:

    @pytest.mark.parametrize("query", [
        "What does this image show?",
        "Explain this image",
        "Describe this image",
        "What is in this image?",
        "Analyze this image",
        "What does this diagram show?",
        "what does this chart mean",
        "this image?",
    ])
    @patch("agents.intent_classifier.route")
    def test_attached_image_questions_are_vision_not_generation(self, mock_route, query):

        result = IntentClassifier().classify(query, has_image=True)

        assert result["diagram"] is False
        assert result["answer"] is True
        mock_route.assert_not_called()

    @pytest.mark.parametrize("query", [
        "Generate an image of a satellite",
        "Create a picture of a cat",
        "Draw an illustration of the water cycle",
        "Make an image showing photosynthesis",
    ])
    @patch("agents.intent_classifier.route")
    def test_explicit_generation_without_image_generates(self, mock_route, query):

        assert IntentClassifier().classify(query)["diagram"] is True

    @pytest.mark.parametrize("query", [
        "Generate a new image in the style of this one",
        "Create a flowchart from this image",
        "Draw a picture based on this diagram",
    ])
    @patch("agents.intent_classifier.route", return_value='{"diagram": true}')
    def test_explicit_new_visual_with_image_attached_still_generates(self, mock_route, query):

        assert IntentClassifier().classify(query, has_image=True)["diagram"] is True

    @patch("agents.intent_classifier.route")
    def test_llm_path_cannot_add_generation_for_attached_image(self, mock_route):

        # Even if the LLM (or the keyword override) says "diagram", a
        # question about the attachment stays image understanding.
        mock_route.return_value = '{"answer": true, "diagram": true}'

        result = IntentClassifier().classify(
            "hmm, and those arrows in the picture?", has_image=True
        )

        assert result["diagram"] is False

    @patch("agents.intent_classifier.route")
    def test_image_attached_quiz_request_keeps_quiz(self, mock_route):

        result = IntentClassifier().classify("make a quiz from this image", has_image=True)

        assert result["quiz"] is True
        assert result["diagram"] is False

    def test_bare_show_is_not_a_creation_verb_without_image(self):

        # No image attached and no creation verb -> not deterministic
        # generation (goes to the LLM instead).
        assert IntentClassifier().route_deterministically("what does this image show?") is None

    def test_orchestrator_passes_attachment_flag(self):

        orch = _orch_with(_intents(answer=True))
        orch.intent_classifier.classify = MagicMock(return_value=_intents(answer=True))
        orch.vision.analyze_images = MagicMock(return_value={"description": "a diagram"})

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"x")
            path = f.name

        try:
            orch.run("What does this image show?", image_attachments=[
                {"path": path, "mime_type": "image/png", "filename": "a.png"}
            ])
        finally:
            os.remove(path)

        assert orch.intent_classifier.classify.call_args.kwargs["has_image"] is True


# =====================================================
# PRIORITY 5A — chart value parsing
# =====================================================

class TestChartValueParsing:

    @pytest.mark.parametrize("query", [
        "Create a bar chart using A=10, B=20",
        "Create a bar chart using A=10 and B=20",
        "Create a bar chart with A=10 and B=20",
        "bar chart A: 10, B: 20",
        "bar chart A=10 & B=20",
    ])
    def test_labels_are_clean(self, query):

        assert extract_explicit_values(query) == (["A", "B"], [10, 20])

    def test_words_containing_and_are_not_split(self):

        assert extract_explicit_values("sand = 5, band = 7") == (["sand", "band"], [5, 7])


# =====================================================
# PRIORITY 5B — unreadable PDF
# =====================================================

class TestUnreadablePdf:

    def _ingest(self, content: bytes):

        path = os.path.join(tempfile.mkdtemp(), "bad.pdf")
        with open(path, "wb") as f:
            f.write(content)

        with patch("rag.ingest.VectorStore"):
            return PDFIngestor(session_id="s").ingest_pdf(path)

    def test_corrupt_pdf_reports_fixed_safe_message(self):

        result = self._ingest(b"%PDF-1.4 this is not really a pdf")

        assert result == {"status": "error", "message": UNREADABLE_PDF_MESSAGE}

    def test_api_maps_unreadable_pdf_to_422(self):

        from api.pdf import USER_FACING_INGEST_ERRORS

        assert UNREADABLE_PDF_MESSAGE in USER_FACING_INGEST_ERRORS
        assert "corrupted" in USER_FACING_INGEST_ERRORS[UNREADABLE_PDF_MESSAGE]
