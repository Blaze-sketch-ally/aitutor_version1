import json

from langsmith import traceable
from models.errors import LLMQuotaExhaustedError
from models.router import route


# =====================================
# ROLLING SUMMARY POLICY
# =====================================
# The last RECENT_WINDOW messages always go to prompts verbatim (clipped
# per message). Only messages older than that are summarized, and the
# summary is refreshed once REFRESH_EVERY more messages have aged out of
# the window — so short conversations never pay for a summary, and long
# ones pay one small (FAST_MODEL) call every couple of turns instead of
# a full-history summary on every turn. The summary is persisted on the
# session row (sessions.summary) as JSON {"v", "covered", "text"}.

RECENT_WINDOW = 6
REFRESH_EVERY = 4


def plan_summary(message_count: int, covered: int) -> dict:
    """
    Decide how the conversation is split for this turn.

    covered: messages[:covered] are already represented by the stored
    summary. Returns {"refresh": bool, "covered": int, "recent_start":
    int}: when refresh is True, messages[old covered:new covered] must be
    folded into the summary; recent_start is where verbatim history
    begins either way (never leaving a gap between summary and history).
    """

    if covered > message_count:
        covered = 0  # history was truncated below the summary; rebuild

    uncovered = message_count - covered

    if uncovered < RECENT_WINDOW + REFRESH_EVERY:
        return {"refresh": False, "covered": covered, "recent_start": covered}

    new_covered = message_count - RECENT_WINDOW

    return {"refresh": True, "covered": new_covered, "recent_start": new_covered}


def load_stored_summary(raw) -> dict:

    if not raw:
        return {"covered": 0, "text": ""}

    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("v") == 1:
            return {
                "covered": int(data.get("covered", 0)),
                "text": str(data.get("text", "")),
            }
    except (TypeError, ValueError):
        pass

    # Legacy/plain-text value (e.g. written by the old Streamlit app):
    # not ours, ignore it.
    return {"covered": 0, "text": ""}


def dump_stored_summary(covered: int, text: str) -> str:

    return json.dumps({"v": 1, "covered": covered, "text": text})


class ConversationSummaryAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    @traceable(
        name="ConversationSummaryAgent.update_summary"
    )
    def update_summary(
        self,
        previous_summary: str,
        new_messages_text: str
    ) -> str:
        """
        Folds messages that just left the verbatim window into the
        running summary. Input is bounded: the previous summary plus
        only the newly aged-out messages (already clipped per message).
        On failure the previous summary is kept.
        """

        if not new_messages_text.strip():
            return previous_summary

        prompt = f"""
You maintain a short memory of a tutoring conversation for other AI
Tutor agents. Update the memory with the new messages.

RULES:
- Max ~150 words. Bullet points.
- Keep: topics covered, the student's goals, what they struggled with,
  the current focus.
- Record what was DISCUSSED, not what is true. The assistant's earlier
  replies may contain mistakes or general-knowledge claims.
- NEVER write that the PDF/document "says", "states" or "contains"
  something. Other agents check the document themselves; this memory
  must not become a source of document facts.
- No greetings or small talk.

CURRENT MEMORY:
{previous_summary or "(empty)"}

NEW MESSAGES:
{new_messages_text}

Return only the updated memory.
"""

        try:

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="summarize"
            )

            return response.strip()

        except LLMQuotaExhaustedError:

            raise

        except Exception as e:

            print(f"ConversationSummaryAgent Error: {e}")

            return previous_summary

    @traceable(
        name="ConversationSummaryAgent.summarize"
    )
    def summarize(
        self,
        history_text: str,
        current_query: str = ""
    ) -> str:

        # No conversation yet
        if not history_text.strip():
            return ""

        # Skip summarization for very small histories
        if len(history_text) < 300:
            return history_text

        prompt = f"""
You are a Conversation Memory Agent for an AI Tutor.

Your job is to create a concise memory summary that will be
passed to other AI Tutor agents so they can maintain context
across long conversations.

The summary should help another AI Tutor understand:

1. What topic the user is learning
2. What has already been explained
3. Important concepts already covered
4. The user's current learning objective
5. The current focus of discussion

IMPORTANT RULES:

- Keep the summary concise.
- Preserve educational context.
- Preserve user goals.
- Preserve important definitions and concepts.
- Do NOT include greetings.
- Do NOT include small talk.
- Do NOT repeat information.
- Do NOT include irrelevant details.
- Focus only on information useful for continuing the tutoring session.
- Record what was DISCUSSED, not what is true. The assistant's earlier
  replies may contain mistakes or general-knowledge claims.
- NEVER write that the PDF/document "says", "states" or "contains"
  something. Other agents check the document themselves; this summary
  must not become a source of document facts.

==================================================
CURRENT USER QUERY
==================================================

{current_query}

==================================================
CONVERSATION HISTORY
==================================================

{history_text}

==================================================
OUTPUT FORMAT
==================================================

Current Topic:
<main topic>

Subtopics Covered:
- ...
- ...

Important Concepts:
- ...
- ...

Current User Goal:
...

Current Focus:
...

==================================================
SUMMARY
==================================================
"""

        try:

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="summarize"
            )

            return response.strip()

        except Exception as e:

            print(
                f"ConversationSummaryAgent Error: {e}"
            )

            return ""