from langsmith import traceable
from models.router import route
from models.errors import LLMServiceError
from prompts.grounding import (
    CONVERSATION_SECTION_NOTE,
    EVIDENCE_SECTION_TITLE,
    GROUNDING_RULE,
)


class QuizAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    @traceable(name="QuizAgent.generate_quiz")
    def generate_quiz(
        self,
        topic: str,
        difficulty: str = "medium",
        context: str = "",
        history_text: str = "",
        summary: str = "",
        strict_pdf: bool = False
    ):

        # =====================================
        # EMPTY CONTEXT GUARD (strict PDF mode)
        # =====================================
        # Same reasoning as NotesAgent — don't rely on the LLM to
        # notice on its own that context is empty and improvise
        # "Use ONLY PDF context" instructions against nothing.

        if strict_pdf and not context.strip():

            return (
                "I could not find relevant information "
                "inside the uploaded PDF to generate a quiz from."
            )

        if strict_pdf:

            rule_block = """
You are an exam question generator.

STRICT RULES:

- Use ONLY PDF context.
- Do NOT use outside knowledge.
- Use summary and history to resolve references.
"""

        else:

            rule_block = """
Your are Athena , an AI Tutor.

RULES:

- Use PDF context if available.
- Use general knowledge if required.
- Generate meaningful quizzes.
- Use summary first.
- Use history for details.
"""

        prompt = f"""
{rule_block}
{GROUNDING_RULE if context.strip() else ''}

==================================================
CONVERSATION SUMMARY {CONVERSATION_SECTION_NOTE}
==================================================

{summary}

==================================================
CONVERSATION HISTORY {CONVERSATION_SECTION_NOTE}
==================================================

{history_text}

==================================================
{EVIDENCE_SECTION_TITLE}
==================================================

{context}

==================================================
CURRENT REQUEST
==================================================

{topic}

==================================================
DIFFICULTY
==================================================

{difficulty}

==================================================
OUTPUT FORMAT
==================================================

# Multiple Choice Questions (10)

# Viva Questions (5)

# Long Answer Questions (2)

Generate the quiz now.
"""

        # =====================================
        # ERROR HANDLING
        # =====================================
        # Same reasoning as NotesAgent — previously had no try/except
        # at all, so any Groq failure would propagate as an uncaught
        # exception through Orchestrator.run() and crash the request.

        try:

            return route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="quiz"
            )

        except LLMServiceError:

            # Provider failure — let the API report it instead of
            # returning a canned apology as if it were content.
            raise

        except Exception as e:

            print(
                f"QuizAgent Error: {e}"
            )

            return (
                "Sorry, I could not generate a quiz for this "
                "right now."
            )