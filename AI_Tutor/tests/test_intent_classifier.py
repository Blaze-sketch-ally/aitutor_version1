from unittest.mock import patch

from agents.intent_classifier import IntentClassifier


def _base_intents(**overrides):

    base = {
        "chat": False, "answer": True, "quiz": False, "notes": False,
        "diagram": False, "videos": False, "papers": False,
        "comparison": False, "all_pdfs": False, "web_research": False,
        "external_action": False, "knowledge_source": "general",
        "resource_source": "query"
    }

    base.update(overrides)

    return base


class TestExternalActionOverride:

    def test_where_can_i_apply_triggers_external_action(self):

        clf = IntentClassifier()

        result = clf._apply_external_action_override(
            _base_intents(), "where can i apply for a passport"
        )

        assert result["external_action"] is True

    def test_book_me_a_flight_triggers_external_action(self):

        clf = IntentClassifier()

        result = clf._apply_external_action_override(
            _base_intents(), "book me a flight from kolkata to delhi"
        )

        assert result["external_action"] is True

    def test_plain_question_does_not_trigger_external_action(self):

        clf = IntentClassifier()

        result = clf._apply_external_action_override(
            _base_intents(), "how does gradient descent work"
        )

        assert result["external_action"] is False

    def test_answer_suppressed_when_no_explanation_hint(self):

        clf = IntentClassifier()

        intents = _base_intents(answer=True, external_action=True)

        result = clf._apply_external_action_answer_override(
            intents, "where can i apply for a passport"
        )

        assert result["answer"] is False

    def test_answer_kept_when_explanation_also_requested(self):

        clf = IntentClassifier()

        intents = _base_intents(answer=True, external_action=True)

        result = clf._apply_external_action_answer_override(
            intents,
            "explain what aws certification is and tell me where to register"
        )

        assert result["answer"] is True


class TestWebResearchVsExternalActionDistinction:

    def test_latest_news_does_not_trigger_external_action(self):

        clf = IntentClassifier()

        result = clf._apply_external_action_override(
            _base_intents(), "what's the latest news on ai regulation"
        )

        assert result["external_action"] is False

    def test_where_can_i_register_does_not_trigger_web_research(self):

        clf = IntentClassifier()

        result = clf._apply_web_research_override(
            _base_intents(), "where can i register for aws certification"
        )

        assert result["web_research"] is False


class TestClassifyEndToEnd:
    """
    Mocks the LLM call so classify()'s full pipeline (LLM path +
    _apply_overrides) is exercised without hitting a real model —
    verifies the keyword override still catches an external-action
    request even when the LLM step itself misses it (the exact failure
    mode these overrides exist to guard against).
    """

    @patch("agents.intent_classifier.route")
    def test_external_action_query_caught_even_if_llm_misses_it(self, mock_route):

        mock_route.return_value = '{"chat": false, "answer": true}'

        clf = IntentClassifier()
        result = clf.classify("where can I apply for a passport")

        assert result["external_action"] is True
        assert result["answer"] is False
