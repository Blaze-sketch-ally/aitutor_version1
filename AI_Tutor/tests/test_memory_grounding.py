from unittest.mock import patch

import memory.chat_memory as chat_memory_module
from agents.notes_agent import NotesAgent
from agents.tutor_agent import TutorAgent
from memory.conversation_summary import ConversationSummaryAgent
from prompts.grounding import EVIDENCE_SECTION_TITLE, GROUNDING_RULE

# An earlier assistant turn that claimed something the PDF never said.
FABRICATED_TURN = (
    "According to the PDF, the Zephyr handshake runs on port 7777."
)
HISTORY = [
    {"role": "user", "content": "What port does Zephyr use?"},
    {"role": "assistant", "content": FABRICATED_TURN, "sources": []},
]
EVIDENCE = "The Zephyr handshake uses HELLO, CHALLENGE and SEAL messages."


def _memory():

    with patch.object(chat_memory_module, "SessionManager") as mock_sm:
        mock_sm.return_value.get_history.return_value = list(HISTORY)
        return chat_memory_module.ChatMemory(user_id="u", session_id="s")


def _sections(prompt: str):
    """Returns (text before the evidence heading, evidence section)."""

    head, _, evidence = prompt.partition(EVIDENCE_SECTION_TITLE)
    return head, evidence


class TestHistoryIsLabelledAsConversation:

    def test_assistant_turns_are_marked_not_evidence(self):

        text = _memory().get_history_text()

        assert (
            "ASSISTANT (earlier reply, not document evidence): "
            + FABRICATED_TURN
        ) in text
        assert "USER: What port does Zephyr use?" in text


class TestUnsupportedEarlierClaimIsNotPresentedAsPdfFact:

    def _prompt(self, strict):

        return TutorAgent()._build_prompt(
            question="According to the PDF, what port does Zephyr use?",
            context=EVIDENCE,
            history_text=_memory().get_history_text(),
            summary="",
            marks="3",
            strict_pdf=strict
        )

    def test_strict_prompt_keeps_claim_out_of_evidence(self):

        prompt = self._prompt(strict=True)
        head, evidence = _sections(prompt)

        # The fabricated claim is only in the (labelled) conversation...
        assert FABRICATED_TURN in head
        assert "port 7777" not in evidence
        # ...and the model is told conversation isn't evidence.
        assert GROUNDING_RULE.strip() in prompt
        assert "NOT evidence of what the document says" in head

    def test_hybrid_prompt_also_carries_the_rule(self):

        assert GROUNDING_RULE.strip() in self._prompt(strict=False)

    def test_no_rule_noise_when_no_document_involved(self):

        prompt = TutorAgent()._build_prompt(
            question="What is TCP?", context="", history_text="",
            summary="", marks="3", strict_pdf=False
        )

        assert GROUNDING_RULE.strip() not in prompt

    @patch("agents.tutor_agent.route")
    def test_strict_question_without_evidence_never_reaches_llm(self, mock_route):

        # Even with the fabricated claim in history, a PDF question with
        # no evidence gets the not-found reply, not the old claim.
        answer = TutorAgent().generate_answer(
            question="According to the PDF, what port does Zephyr use?",
            context="",
            history_text=_memory().get_history_text(),
            strict_pdf=True
        )

        mock_route.assert_not_called()
        assert "7777" not in answer

    @patch("agents.notes_agent.route", return_value="notes")
    def test_notes_prompt_carries_the_rule(self, mock_route):

        NotesAgent().generate_notes(
            topic="notes on Zephyr from the pdf",
            context=EVIDENCE,
            history_text=_memory().get_history_text(),
            strict_pdf=True
        )

        prompt = mock_route.call_args.kwargs["prompt"]
        assert GROUNDING_RULE.strip() in prompt
        assert "port 7777" not in _sections(prompt)[1]


class TestSummaryDoesNotMintDocumentFacts:

    @patch("memory.conversation_summary.route", return_value="summary")
    def test_summary_prompt_forbids_pdf_fact_statements(self, mock_route):

        ConversationSummaryAgent().summarize(
            history_text=_memory().get_history_text() * 5,
            current_query="and the port?"
        )

        prompt = mock_route.call_args.kwargs["prompt"]
        assert 'NEVER write that the PDF/document "says"' in prompt
