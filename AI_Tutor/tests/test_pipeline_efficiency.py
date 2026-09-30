"""
Phase 9-12 regression tests: each expensive stage runs at most the
expected number of times per user message, history sent to models is
bounded, and the conversation summary is only produced when needed.
"""

from unittest.mock import MagicMock

import pytest

from agents.query_resolver import QueryResolverAgent
from memory.chat_memory import ChatMemory
from memory.conversation_summary import (
    RECENT_WINDOW,
    REFRESH_EVERY,
    dump_stored_summary,
    load_stored_summary,
    plan_summary,
)

from tests.test_orchestrator_routing import _intents
from tests.test_pdf_retrieval_routing import _orch_with


def _long_history(n, answer_len=3000):

    messages = []

    for i in range(n // 2):
        messages.append({"role": "user", "content": f"question {i} about TCP"})
        messages.append({"role": "assistant", "content": "A" * answer_len})

    return messages


def _with_history(orch, messages):

    orch.memory.get_full_history = MagicMock(return_value=list(messages))
    orch.memory.history = list(messages)
    orch.memory.format_messages = ChatMemory.format_messages
    # Real formatting on the mocked memory's buffer.
    orch.memory.get_history_text = (
        lambda **kw: ChatMemory.get_history_text(orch.memory, **kw)
    )
    orch.memory.add_message = lambda role=None, content=None, message=None, **_: (
        orch.memory.history.append(message or {"role": role, "content": content})
    )


class TestStagesRunOncePerMessage:

    def _stage_mocks(self, orch):

        orch.intent_classifier.classify = MagicMock(
            wraps=orch.intent_classifier.classify
        )
        orch.query_resolver.resolve = MagicMock(
            return_value={"resolved_query": "resolved"}
        )
        orch.summary_agent.update_summary = MagicMock(return_value="memory")
        orch.notes.generate_notes = MagicMock(return_value="notes")
        orch.quiz.generate_quiz = MagicMock(return_value="quiz")

    @pytest.mark.parametrize("query, intents, agent", [
        ("Generate notes from the PDF", _intents(notes=True, knowledge_source="pdf"), "notes"),
        ("Generate a quiz from the PDF", _intents(quiz=True, knowledge_source="pdf"), "quiz"),
    ])
    def test_stream_fallback_does_not_repeat_pipeline(self, query, intents, agent):

        orch = _orch_with(intents)
        self._stage_mocks(orch)
        orch.intent_classifier.classify = MagicMock(return_value=intents)

        result = orch.run_stream(query, selected_pdfs=["a.pdf"])

        assert result["streamed"] is False
        # Used to be 2 classifier + 2 resolver calls (run_stream, then
        # again inside run()).
        assert orch.intent_classifier.classify.call_count == 1
        assert orch.query_resolver.resolve.call_count == 0
        assert orch.retriever.get_context_with_sources.call_count == 1
        generate = getattr(getattr(orch, agent), f"generate_{agent}")
        assert generate.call_count == 1

    def test_streamed_answer_classifies_and_retrieves_once(self):

        orch = _orch_with(_intents(answer=True), context="TCP text")
        orch.intent_classifier.classify = MagicMock(return_value=_intents(answer=True))
        orch.tutor.generate_answer_stream = MagicMock(return_value=iter(["x"]))

        result = orch.run_stream("How does TCP work?", selected_pdfs=["a.pdf"])

        assert result["streamed"] is True
        assert orch.intent_classifier.classify.call_count == 1
        assert orch.retriever.get_context_with_sources.call_count == 1

    def test_video_turn_skips_resolver_and_classifier(self):

        orch = _orch_with(_intents(answer=True))
        _with_history(orch, _long_history(4, 50))
        orch.intent_classifier.classify = MagicMock()
        orch.query_resolver.resolve = MagicMock()
        orch.video_summary.summarize_video = MagicMock(return_value={"summary": "s"})

        orch.run_stream("summarize https://www.youtube.com/watch?v=dQw4w9WgXcQ it")

        orch.intent_classifier.classify.assert_not_called()
        orch.query_resolver.resolve.assert_not_called()

    def test_user_message_tracked_once(self):

        orch = _orch_with(_intents(notes=True))
        _with_history(orch, [])
        orch.intent_classifier.classify = MagicMock(return_value=_intents(notes=True))
        orch.notes.generate_notes = MagicMock(return_value="notes")

        orch.run_stream("Generate notes on TCP", selected_pdfs=[])

        users = [m for m in orch.memory.history if m.get("role") == "user"]
        assert len(users) == 1


class TestResolverOnlyWhenNeeded:

    @pytest.mark.parametrize("query, has_history, expected", [
        ("How does TCP detect packet loss?", False, False),
        ("How does TCP detect packet loss?", True, False),
        ("What is the reference course code for this chapter?", False, False),
        ("why is that needed?", True, True),
        ("explain it simply", True, True),
        ("why?", True, True),
        ("and UDP?", True, True),
        ("examples", True, True),
        ("Generate notes on photosynthesis", True, False),
    ])
    def test_needs_resolution(self, query, has_history, expected):

        assert QueryResolverAgent.needs_resolution(query, has_history) is expected

    def test_self_contained_question_skips_resolver_llm(self):

        orch = _orch_with(_intents(answer=True))
        _with_history(orch, _long_history(4, 50))
        orch.query_resolver.resolve = MagicMock()

        orch.run("How does TCP detect packet loss?", selected_pdfs=[])

        orch.query_resolver.resolve.assert_not_called()

    def test_referring_question_is_resolved_with_bounded_history(self):

        orch = _orch_with(_intents(answer=True))
        _with_history(orch, _long_history(10, 5000))
        orch.summary_agent.update_summary = MagicMock(return_value="memory")
        orch.session_manager.load_session = MagicMock(return_value={"summary": None})
        orch.query_resolver.resolve = MagicMock(return_value={"resolved_query": "Why is slow start needed?"})

        orch.run("why is that needed?", selected_pdfs=[])

        kwargs = orch.query_resolver.resolve.call_args.kwargs
        # 4 messages, clipped — not 10 full 5k-char answers.
        assert len(kwargs["history_text"]) < 4000


class TestSummaryPolicy:

    def test_short_conversation_never_summarized(self):

        for n in range(0, RECENT_WINDOW + REFRESH_EVERY):
            assert plan_summary(n, 0)["refresh"] is False

    def test_refresh_only_every_few_messages(self):

        first = plan_summary(RECENT_WINDOW + REFRESH_EVERY, 0)
        assert first["refresh"] is True
        covered = first["covered"]

        # Next turn (+2 messages): reuse, no LLM call.
        assert plan_summary(RECENT_WINDOW + REFRESH_EVERY + 2, covered)["refresh"] is False
        # History window starts where the summary ends — no gap.
        assert plan_summary(RECENT_WINDOW + REFRESH_EVERY + 2, covered)["recent_start"] == covered

    def test_truncated_history_invalidates_summary(self):

        assert plan_summary(3, 12) == {"refresh": False, "covered": 0, "recent_start": 0}

    def test_stored_summary_round_trip_and_legacy_values(self):

        assert load_stored_summary(dump_stored_summary(8, "memo")) == {"covered": 8, "text": "memo"}
        assert load_stored_summary("plain legacy text") == {"covered": 0, "text": ""}
        assert load_stored_summary(None) == {"covered": 0, "text": ""}

    def test_long_conversation_summarized_once_then_reused(self):

        orch = _orch_with(_intents(answer=True))
        messages = _long_history(RECENT_WINDOW + REFRESH_EVERY, 500)
        _with_history(orch, messages)
        stored = {"summary": None}
        orch.session_manager.load_session = MagicMock(side_effect=lambda _sid: dict(stored))
        orch.session_manager.update_summary = MagicMock(
            side_effect=lambda _sid, value: stored.update(summary=value)
        )
        orch.summary_agent.update_summary = MagicMock(return_value="memory")

        orch.run("How does TCP work?", selected_pdfs=[])
        assert orch.summary_agent.update_summary.call_count == 1

        # Next turn: two more messages, summary reused (no new call).
        _with_history(orch, messages + _long_history(2, 500))
        orch.run("How does UDP work?", selected_pdfs=[])
        assert orch.summary_agent.update_summary.call_count == 1

        _, kwargs = orch.tutor.generate_answer.call_args
        assert kwargs["summary"] == "memory"


class TestHistoryBudgets:

    def test_agent_history_is_clipped(self):

        orch = _orch_with(_intents(answer=True))
        _with_history(orch, _long_history(8, 5000))
        orch.session_manager.load_session = MagicMock(return_value={"summary": None})

        orch.run("How does TCP work?", selected_pdfs=[])

        _, kwargs = orch.tutor.generate_answer.call_args
        # 8 prior messages of 5k chars = 40k+; clipped window is far less.
        assert len(kwargs["history_text"]) < 12000
        assert "…[truncated]" in kwargs["history_text"]

    def test_format_messages_keeps_latest_messages_larger(self):

        text = ChatMemory.format_messages(
            [{"role": "assistant", "content": "x" * 5000}] * 3,
            max_chars=100, latest_max_chars=1000
        )
        lines = text.splitlines()

        assert len(lines[0]) < 200
        assert len(lines[-1]) > 900
