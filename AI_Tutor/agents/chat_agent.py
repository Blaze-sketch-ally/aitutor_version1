from langsmith import traceable
from models.router import route, route_stream
from models.errors import LLMServiceError


class ChatAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    # =====================================
    # PROMPT BUILDING (shared by streaming and non-streaming
    # generation — kept in one place so the two methods below can
    # never drift out of sync with each other)
    # =====================================

    def _build_prompt(
        self,
        message: str,
        conversation_history: list = None,
        history_text: str = "",
        summary: str = ""
    ) -> str:

        if not history_text:

            history_text = ""

            if conversation_history:

                recent_history = conversation_history[-10:]

                for item in recent_history:

                    role = item.get(
                        "role",
                        "user"
                    )

                    content = item.get(
                        "content",
                        ""
                    )

                    history_text += (
                        f"{role.upper()}: "
                        f"{content}\n"
                    )

        return f"""
Your are Athena , an AI Tutor.

PERSONALITY

- Friendly
- Helpful
- Conversational
- Patient
- Student-focused

RULES

- Use conversation summary first.
- Use conversation history for details.
- Resolve follow-up questions.
- Continue naturally.
- Never invent previous conversation details.

==================================================
CONVERSATION SUMMARY
==================================================

{summary}

==================================================
CONVERSATION HISTORY
==================================================

{history_text}

==================================================
CURRENT USER MESSAGE
==================================================

{message}

==================================================
ASSISTANT RESPONSE
==================================================
"""

    # =====================================
    # REPLY GENERATION (non-streaming)
    # =====================================
    # Unchanged behavior — kept for any caller that still wants the
    # complete string in one shot (e.g. Orchestrator.run(), the
    # non-streaming fallback path).

    @traceable(
        name="ChatAgent.generate_reply"
    )
    def generate_reply(
        self,
        message: str,
        conversation_history: list = None,
        history_text: str = "",
        summary: str = ""
    ):

        prompt = self._build_prompt(
            message=message,
            conversation_history=conversation_history,
            history_text=history_text,
            summary=summary
        )

        try:

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="chat"
            )

            return response.strip()

        except LLMServiceError:

            # Provider failure — let the API report it instead of
            # returning a canned apology as if it were content.
            raise

        except Exception as e:

            print(f"ChatAgent Error: {e}")

            return (
                "Sorry, I could not generate a reply."
            )

    # =====================================
    # REPLY GENERATION (streaming)
    # =====================================
    # Used by Orchestrator.run_stream() for the pure-chat case (no
    # other intents requested this turn) — the same prompt as
    # generate_reply() above, just yielded incrementally instead of
    # returned as one complete string.

    def generate_reply_stream(
        self,
        message: str,
        conversation_history: list = None,
        history_text: str = "",
        summary: str = ""
    ):

        prompt = self._build_prompt(
            message=message,
            conversation_history=conversation_history,
            history_text=history_text,
            summary=summary
        )

        def _stream():

            try:

                for chunk in route_stream(
                    prompt=prompt,
                    provider=self.provider,
                    model=self.model,
                    purpose="chat"
                ):

                    yield chunk

            except LLMServiceError:

                # Provider failure — let the API report it instead of
                # returning a canned apology as if it were content.
                raise

            except Exception as e:

                print(f"ChatAgent stream error: {e}")

                yield "Sorry, I could not generate a reply."

        return _stream()