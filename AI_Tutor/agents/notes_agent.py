from langsmith import traceable
from models.router import route
from models.errors import LLMServiceError
from prompts.grounding import (
    CONVERSATION_SECTION_NOTE,
    EVIDENCE_SECTION_TITLE,
    GROUNDING_RULE,
)


class NotesAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    @traceable(name="NotesAgent.generate_notes")
    def generate_notes(
        self,
        topic: str,
        context: str = "",
        history_text: str = "",
        summary: str = "",
        strict_pdf: bool = False
    ):

        # =====================================
        # EMPTY CONTEXT GUARD (strict PDF mode)
        # =====================================
        # Matches TutorAgent's existing behavior. Without this, an
        # empty context still got sent into the "use ONLY PDF
        # context" prompt and relied entirely on the LLM to notice
        # there's nothing there and say so — inconsistent in
        # practice. Fail fast with a clear message instead.

        if strict_pdf and not context.strip():

            return (
                "I could not find relevant information "
                "inside the uploaded PDF to generate notes from."
            )

        if strict_pdf:

            rule_block = """
You are an academic tutor.

STRICT RULES:

- Use ONLY PDF context.
- Do NOT use external knowledge.
- If information is missing say:
  "Not found in PDF".

- Use conversation summary and history
  to resolve references.
"""

        else:

            rule_block = """
Your are Athena , an AI Tutor.

RULES:

- Use PDF context if available.
- Use general knowledge if needed.
- Generate high-quality exam notes.
- Use conversation summary first.
- Use conversation history for details.
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
OUTPUT FORMAT
==================================================

# Topic Overview

# Key Concepts

# Important Points

# Formulas (if applicable)

# Quick Revision Notes

Generate notes now.
"""

        # =====================================
        # ERROR HANDLING
        # =====================================
        # Previously this had no try/except at all — any Groq
        # failure (including the new behavior where generate() raises
        # on an empty completion instead of silently returning "")
        # would propagate as an UNCAUGHT exception all the way up
        # through Orchestrator.run() (which doesn't wrap this call in
        # its own try/except either) and crash the whole request
        # instead of failing gracefully.

        try:

            return route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="notes"
            )

        except LLMServiceError:

            # Provider failure — let the API report it instead of
            # returning a canned apology as if it were content.
            raise

        except Exception as e:

            print(
                f"NotesAgent Error: {e}"
            )

            return (
                "Sorry, I could not generate notes for this "
                "right now."
            )