from unittest.mock import MagicMock, patch

import pytest

from agents.intent_classifier import IntentClassifier
from rag.retriever import query_topic_terms

from tests.test_orchestrator_routing import (
    _intents,
    _make_orchestrator_with_mocks,
)


def _orch_with(intents, context="", representative=None):

    orch = _make_orchestrator_with_mocks()

    orch.intent_classifier.classify = MagicMock(return_value=intents)
    orch.summary_agent.summarize = MagicMock(return_value="")
    orch.query_resolver.resolve = MagicMock(
        side_effect=lambda query, **_: {"resolved_query": query}
    )
    orch.retriever.has_documents = MagicMock(return_value=True)
    orch.retriever.get_context_with_sources = MagicMock(return_value={
        "context": context,
        "sources": [{"source": "a.pdf", "page": 1}] if context else []
    })
    orch.retriever.get_representative_context = MagicMock(
        return_value=representative or {}
    )
    orch.tutor.generate_answer = MagicMock(return_value="answer")

    return orch


class TestSelectedPdfRouting:

    def test_how_question_with_selected_pdf_attempts_retrieval(self):

        # The follow-up shortcut classifies "how ..." as general; a
        # selected PDF must still be searched.
        orch = _orch_with(_intents(answer=True), context="TCP slow start...")

        orch.run("how does slow start work", selected_pdfs=["a.pdf"])

        orch.retriever.get_context_with_sources.assert_called_once()
        _, kwargs = orch.tutor.generate_answer.call_args
        assert "slow start" in kwargs["context"]
        assert kwargs["strict_pdf"] is False
        assert kwargs["pdf_searched"] is True

    def test_general_question_without_selected_pdf_skips_retrieval(self):

        orch = _orch_with(_intents(answer=True))

        orch.run("how does slow start work", selected_pdfs=[])

        orch.retriever.get_context_with_sources.assert_not_called()
        _, kwargs = orch.tutor.generate_answer.call_args
        assert kwargs["pdf_searched"] is False

    def test_pure_chat_with_selected_pdf_skips_retrieval(self):

        orch = _orch_with(_intents(chat=True))
        orch.chat.generate_reply = MagicMock(return_value="hello!")

        orch.run("hi there", selected_pdfs=["a.pdf"])

        orch.retriever.get_context_with_sources.assert_not_called()

    def test_explicit_phrase_is_strict_even_if_classifier_says_general(self):

        orch = _orch_with(_intents(answer=True), context="Fast recovery...")

        orch.run(
            "According to the PDF, what is fast recovery?",
            selected_pdfs=["a.pdf"]
        )

        _, kwargs = orch.tutor.generate_answer.call_args
        assert kwargs["strict_pdf"] is True

    def test_unanswerable_specific_question_gets_no_padding(self):

        # No relevant chunk -> no representative sample either; the
        # tutor sees empty context in strict mode and says so.
        orch = _orch_with(
            _intents(answer=True),
            context="",
            representative={"a.pdf": "unrelated sample text"}
        )

        orch.run(
            "According to the PDF, what is the capital of France?",
            selected_pdfs=["a.pdf"]
        )

        orch.retriever.get_representative_context.assert_not_called()
        _, kwargs = orch.tutor.generate_answer.call_args
        assert kwargs["context"] == ""
        assert kwargs["strict_pdf"] is True

    def test_whole_document_request_uses_representative_fallback(self):

        orch = _orch_with(
            _intents(answer=True, knowledge_source="pdf"),
            context="",
            representative={"a.pdf": "sample of the pdf"}
        )

        orch.run("summarize the uploaded pdf", selected_pdfs=["a.pdf"])

        orch.retriever.get_representative_context.assert_called_once()
        _, kwargs = orch.tutor.generate_answer.call_args
        assert "sample of the pdf" in kwargs["context"]


class TestIntentClassifierPdfSignals:

    @pytest.mark.parametrize("query", [
        "According to the PDF, what is X?",
        "from the document, explain Y",
        "in the uploaded file, what does Z do?",
        "summarize this material",
    ])
    def test_references_pdf_detects_explicit_phrases(self, query):

        assert IntentClassifier.references_pdf(query)

    @pytest.mark.parametrize("query", [
        "how does TCP work",
        "how do I open a file in python",
        "make notes on photosynthesis",
    ])
    def test_references_pdf_ignores_generic_wording(self, query):

        assert not IntentClassifier.references_pdf(query)

    @patch("agents.intent_classifier.route")
    def test_followup_word_does_not_swallow_quiz_request(self, mock_route):

        # "how" must not turn a quiz request into answer-only. Since
        # Phase 10 this is decided deterministically (no LLM call);
        # previously it fell through to the LLM classifier.
        result = IntentClassifier().classify("make a quiz on how TCP works")

        mock_route.assert_not_called()
        assert result["quiz"] is True
        assert result["answer"] is False

    @patch("agents.intent_classifier.route")
    def test_plain_followup_still_uses_shortcut(self, mock_route):

        result = IntentClassifier().classify("why?")

        mock_route.assert_not_called()
        assert result["answer"] is True


class TestWholeDocumentDetection:

    @pytest.mark.parametrize("query", [
        "Generate notes from the PDF",
        "summarize the uploaded pdf",
        "Make a quiz from my document",
        "Compare the two PDFs",
    ])
    def test_whole_document_requests_have_no_topic_terms(self, query):

        assert query_topic_terms(query) == set()

    def test_specific_topic_is_kept(self):

        assert "photosynthesis" in query_topic_terms(
            "Generate notes on photosynthesis from the PDF"
        )
