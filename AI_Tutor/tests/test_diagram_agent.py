from unittest.mock import patch

import pytest

from agents.diagram_agent import DiagramAgent, _keyword_type, sanitize_mermaid


class TestDiagramKeywordRouting:

    @pytest.mark.parametrize("query, expected", [
        ("Create a flowchart of TCP connection establishment", "mermaid"),
        ("flowchart of TCP", "mermaid"),
        ("draw a flowchart of the login process", "mermaid"),
        ("Draw an architecture diagram of a RAG system", "mermaid"),
        ("Create a sequence diagram for login", "mermaid"),
        ("make a mind map of photosynthesis", "mermaid"),
        ("show me an org chart of a company", "mermaid"),
        ("Create a bar chart using these values: A=10, B=20", "chart"),
        ("pie chart of market share", "chart"),
        ("plot a histogram of exam scores", "chart"),
        ("Generate an image of a satellite", "image"),
        ("show me a picture of the eiffel tower", "image"),
        ("draw a cat", "image"),
        ("a photograph of a mountain", "image"),
        ("generate a parabolic graph", "math_chart"),
        ("plot y = x^2 + 3", "math_chart"),
        ("diagram of the water cycle", "mermaid"),
        ("explain recursion", None),
    ])
    def test_routes_to_expected_type(self, query, expected):

        assert _keyword_type(query) == expected

    def test_flowchart_is_not_matched_as_chart_substring(self):

        # "chart" inside "flowchart" used to win.
        assert _keyword_type("flowchart") == "mermaid"

    def test_photograph_is_not_matched_as_graph_substring(self):

        assert _keyword_type("photograph of a bridge") == "image"

    @patch("agents.diagram_agent.route", return_value="flowchart")
    def test_llm_type_answer_uses_whole_words(self, _):

        # A model answering "flowchart" must not be read as "chart".
        assert DiagramAgent()._classify_type("x", "", "") == "mermaid"


class TestSanitizeMermaid:

    def test_parentheses_in_label_are_quoted(self):

        out = sanitize_mermaid(
            "flowchart TD\n C[Client: SEAL (128-bit nonce)] --> D[Done]"
        )

        assert 'C["Client: SEAL (128-bit nonce)"]' in out
        assert 'D["Done"]' in out

    def test_brackets_braces_and_quotes_in_labels(self):

        out = sanitize_mermaid(
            'flowchart TD\n A[plain "inner" quote] --> B{Is x > [0]?}'
        )

        assert 'A["plain #quot;inner#quot; quote"]' in out
        assert 'B{"Is x > [0]?"}' in out

    def test_edge_labels_are_quoted(self):

        out = sanitize_mermaid("flowchart TD\n A -->|call f(x)| B")

        assert '|"call f(x)"|' in out

    def test_fences_and_preamble_are_removed(self):

        out = sanitize_mermaid(
            "Here you go:\n```mermaid\ngraph LR\n A[a] --> B[b]\n```"
        )

        assert out.startswith("graph LR")
        assert "```" not in out

    def test_style_lines_are_left_alone(self):

        out = sanitize_mermaid(
            "flowchart TD\n A[x] --> B[y]\n classDef red fill:#f00\n class B red"
        )

        assert "classDef red fill:#f00" in out
        assert "class B red" in out

    def test_sequence_message_semicolons_removed(self):

        out = sanitize_mermaid(
            "sequenceDiagram\n U->>S: POST /login {user; pass}"
        )

        assert "{user, pass}" in out

    def test_missing_header_defaults_to_flowchart(self):

        assert sanitize_mermaid("A[x] --> B[y]").startswith("flowchart TD")


class TestImagePromptPrivacy:

    @patch("agents.diagram_agent.route", return_value="a satellite in orbit")
    def test_pdf_context_is_not_sent_to_image_prompt(self, mock_route):

        DiagramAgent().generate_diagram(
            topic="Generate an image of a satellite",
            context="CONFIDENTIAL_PDF_TEXT_123"
        )

        for call in mock_route.call_args_list:
            assert "CONFIDENTIAL_PDF_TEXT_123" not in call.kwargs["prompt"]


class TestChartsDoNotInventNumbers:

    CHART = '{"chart_type": "bar", "title": "T", "labels": ["a", "b"], "datasets": [{"label": "s", "data": [%s, %s]}]}'

    @patch("agents.diagram_agent.route")
    def test_user_supplied_values_are_charted_without_llm(self, mock_route):

        out = DiagramAgent().generate_diagram(
            "Create a bar chart using these values: A=10, B=20"
        )

        mock_route.assert_not_called()
        assert out["type"] == "chart"
        assert out["content"]["labels"] == ["A", "B"]
        assert out["content"]["datasets"][0]["data"] == [10, 20]

    @patch("agents.diagram_agent.route")
    def test_numbers_found_in_context_are_accepted(self, mock_route):

        mock_route.return_value = self.CHART % (1986, 128)

        out = DiagramAgent().generate_diagram(
            "bar chart of the numbers in the pdf",
            context="Collapse was seen in 1986. SEAL carries a 128-bit nonce."
        )

        assert out["type"] == "chart"

    @patch("agents.diagram_agent.route")
    def test_invented_number_is_rejected(self, mock_route):

        # 42 appears nowhere in the context or request.
        mock_route.return_value = self.CHART % (1986, 42)

        out = DiagramAgent().generate_diagram(
            "bar chart of the numbers in the pdf",
            context="Collapse was seen in 1986. No other figures here."
        )

        assert out["type"] == "none"
        assert out["message"] == DiagramAgent.NO_CHART_DATA_MESSAGE

    @patch("agents.diagram_agent.route", return_value='{"insufficient_data": true}')
    def test_model_can_decline_for_lack_of_data(self, _):

        out = DiagramAgent().generate_diagram(
            "bar chart of packet loss rates from the pdf",
            context="TCP uses slow start and congestion avoidance."
        )

        assert out["type"] == "none"

    @patch("agents.diagram_agent.route")
    def test_strict_pdf_without_context_does_not_call_llm(self, mock_route):

        out = DiagramAgent().generate_diagram(
            "bar chart of loss rates from the pdf", context="", strict_pdf=True
        )

        mock_route.assert_not_called()
        assert out["message"] == DiagramAgent.NO_CHART_DATA_MESSAGE

    @patch("agents.diagram_agent.route")
    def test_general_knowledge_chart_is_labelled(self, mock_route):

        mock_route.return_value = self.CHART % (8, 9)

        out = DiagramAgent().generate_diagram("bar chart of planets' moons")

        assert out["type"] == "chart"
        assert "general knowledge" in out["content"]["title"]

    def test_history_numbers_do_not_count_as_evidence(self):

        # Grounding only accepts numbers from context + request.
        from agents.diagram_agent import _chart_values_are_grounded, _numbers_in

        data = {"datasets": [{"data": [55, 1986]}]}
        allowed = _numbers_in("Collapse was seen in 1986.")

        assert not _chart_values_are_grounded(data, allowed)


class TestNoDataChartBecomesText:

    def test_orchestrator_turns_none_diagram_into_answer_text(self):

        from tests.test_orchestrator_routing import _intents
        from tests.test_pdf_retrieval_routing import _orch_with
        from unittest.mock import MagicMock

        orch = _orch_with(_intents(diagram=True))
        orch.diagram.generate_diagram = MagicMock(return_value={
            "type": "none", "message": DiagramAgent.NO_CHART_DATA_MESSAGE
        })

        result = orch.run("bar chart of loss rates from the pdf", selected_pdfs=["a.pdf"])

        assert "diagram" not in result
        assert DiagramAgent.NO_CHART_DATA_MESSAGE in result["answer"]
