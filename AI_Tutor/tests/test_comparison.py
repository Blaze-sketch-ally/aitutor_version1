from unittest.mock import MagicMock, patch

from agents.comparison_agent import ComparisonAgent

from tests.test_orchestrator_routing import _intents
from tests.test_pdf_retrieval_routing import _orch_with


class TestComparisonAgentModes:

    @patch("agents.comparison_agent.route", return_value="CNN vs RNN table")
    def test_general_comparison_without_pdf(self, mock_route):

        out = ComparisonAgent().generate_comparison(
            topic="Compare CNN and RNN", pdf_contexts={}
        )

        # Used to be the canned "No PDF information available".
        assert out == "CNN vs RNN table"
        prompt = mock_route.call_args.kwargs["prompt"]
        assert "Use your own knowledge" in prompt

    @patch("agents.comparison_agent.route", return_value="x")
    def test_unrelated_selected_pdf_is_disclosed_not_cited(self, mock_route):

        ComparisonAgent().generate_comparison(
            topic="Compare CNN and RNN", pdf_contexts={}, pdf_searched=True
        )

        prompt = mock_route.call_args.kwargs["prompt"]
        assert "doesn't cover this" in prompt
        assert "Never claim or imply that the PDF says anything" in prompt

    @patch("agents.comparison_agent.route")
    def test_strict_pdf_comparison_with_no_evidence_does_not_call_llm(self, mock_route):

        out = ComparisonAgent().generate_comparison(
            topic="According to my PDF, compare CNN and RNN",
            pdf_contexts={},
            strict_pdf=True
        )

        mock_route.assert_not_called()
        assert "couldn't find" in out

    @patch("agents.comparison_agent.route", return_value="x")
    def test_strict_concept_comparison_uses_only_pdf(self, mock_route):

        ComparisonAgent().generate_comparison(
            topic="Compare Tahoe and Reno",
            pdf_contexts={"tcp.pdf": "Tahoe resets cwnd; Reno halves it."},
            strict_pdf=True
        )

        prompt = mock_route.call_args.kwargs["prompt"]
        assert "Use ONLY the PDF evidence" in prompt
        assert "Tahoe resets cwnd" in prompt


class TestComparisonRouting:

    def _run(self, query, selected, grouped_contexts, intents=None):

        orch = _orch_with(intents or _intents(comparison=True))
        orch.retriever.get_grouped_context_by_source = MagicMock(
            return_value={"pdf_contexts": grouped_contexts, "sources": []}
        )
        orch.comparison.generate_comparison = MagicMock(return_value="cmp")

        orch.run(query, selected_pdfs=selected)

        return orch, orch.comparison.generate_comparison.call_args.kwargs

    def test_no_pdf_selected_is_general_and_not_searched(self):

        orch, kwargs = self._run("Compare CNN and RNN", [], {})

        orch.retriever.get_grouped_context_by_source.assert_not_called()
        assert kwargs["pdf_contexts"] == {}
        assert kwargs["pdf_searched"] is False
        assert kwargs["strict_pdf"] is False

    def test_unrelated_selected_pdf_falls_back_to_general(self):

        orch, kwargs = self._run("Compare CNN and RNN", ["tcp.pdf"], {})

        orch.retriever.get_grouped_context_by_source.assert_called_once()
        orch.retriever.get_representative_context.assert_not_called()
        assert kwargs["pdf_contexts"] == {}
        assert kwargs["pdf_searched"] is True
        assert kwargs["strict_pdf"] is False

    def test_selected_pdf_with_relevant_evidence_is_used(self):

        _, kwargs = self._run(
            "Compare Tahoe and Reno", ["tcp.pdf"], {"tcp.pdf": "Tahoe..."}
        )

        assert kwargs["pdf_contexts"] == {"tcp.pdf": "Tahoe..."}
        assert kwargs["compare_documents"] is False

    def test_explicit_pdf_comparison_is_strict(self):

        _, kwargs = self._run(
            "According to my PDF, compare Tahoe and Reno",
            ["tcp.pdf"],
            {"tcp.pdf": "Tahoe..."}
        )

        assert kwargs["strict_pdf"] is True

    def test_compare_the_pdfs_compares_documents(self):

        _, kwargs = self._run(
            "Compare the two PDFs",
            ["a.pdf", "b.pdf"],
            {"a.pdf": "A", "b.pdf": "B"}
        )

        assert kwargs["compare_documents"] is True
