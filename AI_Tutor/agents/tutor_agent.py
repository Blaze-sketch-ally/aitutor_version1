import re

from langsmith import traceable
from models.router import route, route_stream
from models.errors import LLMServiceError
from prompts.grounding import (
    CONVERSATION_SECTION_NOTE,
    EVIDENCE_SECTION_TITLE,
    GROUNDING_RULE,
)


class TutorAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    # =====================================
    # AUTO MARKS DETECTION
    # =====================================

    def detect_marks(
        self,
        question: str
    ) -> str:

        q = question.lower()

        match = re.search(
            r"(3|5|6|8|10|15)\s*mark",
            q
        )

        if match:
            return match.group(1)

        if "short note" in q:
            return "5"

        if "brief" in q:
            return "3"

        if "very short" in q:
            return "3"

        return "8"

    # =====================================
    # PROMPT BUILDING (shared by streaming and
    # non-streaming generation — kept in one place so the two
    # methods below can never drift out of sync with each other)
    # =====================================

    def _build_prompt(
        self,
        question: str,
        context: str,
        history_text: str,
        summary: str,
        marks: str,
        strict_pdf: bool,
        pdf_searched: bool = False
    ) -> str:

        # =====================================
        # KNOWLEDGE MODE
        # =====================================

        if strict_pdf:

            rule_block = """
Your are Athena , an AI Tutor.

Answer ONLY from the RETRIEVED DOCUMENT EVIDENCE.

STRICT RULES:

- Use ONLY PDF information.
- Do NOT use external knowledge.
- Do NOT invent facts.
- If the RETRIEVED DOCUMENT EVIDENCE does not contain the answer, say exactly:

"This information is not available in the uploaded PDF."

  and do not answer from general knowledge.

- Maintain a conversational tutoring style.
- Use conversation summary and history ONLY to resolve references
  (what "it"/"that" means) — never as a source of facts.
"""

        elif context.strip():

            rule_block = """
Your are Athena , an AI Tutor.

Use the RETRIEVED DOCUMENT EVIDENCE as the PRIMARY source.

You may supplement with your own knowledge
when useful.

RULES:

- Combine PDF information and general knowledge.
- Only attribute to the PDF what the RETRIEVED DOCUMENT EVIDENCE actually says.
- If the RETRIEVED DOCUMENT EVIDENCE does not answer the question, say briefly that
  the selected PDF doesn't cover it, then answer from general
  knowledge.
- Explain concepts clearly.
- Use examples whenever useful.
- Maintain a conversational tutoring style.
- Use conversation summary and history when relevant.
"""

        elif pdf_searched:

            # PDFs were selected/searched but nothing relevant was
            # found — be upfront about that instead of answering as if
            # the material said something.
            rule_block = """
Your are Athena , an AI Tutor.

The student has PDF material selected, but no passage in it is
relevant to this question.

RULES:

- Start with one short sentence saying the selected PDF doesn't
  appear to cover this, so you're answering from general knowledge.
- Never claim or imply that the PDF says anything.
- If you are not confident of the answer, say so instead of guessing.
- Be educational and conversational.
- Use conversation summary and history when relevant.
"""

        else:

            rule_block = """
Your are Athena , an AI Tutor.

Use your own knowledge.

RULES:

- Be educational.
- Be conversational.
- Explain concepts clearly.
- Use examples.
- Use conversation summary and history when relevant.
"""

        # =====================================
        # MARKS INSTRUCTION
        # =====================================

        marks_instruction = f"""
Generate an answer suitable for {marks} marks.

3 Marks:
- concise
- 3-4 points

5 Marks:
- short explanation
- key concepts

6 Marks:
- moderate detail

8 Marks:
- detailed explanation
- examples

10 Marks:
- comprehensive explanation
- examples
- applications

15 Marks:
- full descriptive answer
- advantages
- disadvantages
- applications
- conclusion
"""

        # =====================================
        # FINAL PROMPT
        # =====================================

        grounding_rule = GROUNDING_RULE if context.strip() else ""

        return f"""
{rule_block}
{grounding_rule}
{marks_instruction}

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
FOLLOW-UP RESOLUTION RULES
==================================================

If the question is a follow-up such as:

- why?
- how?
- explain more
- continue
- give example
- advantages?
- disadvantages?
- compare them
- diagram of it
- applications?

Then use the conversation summary and history
to determine the actual topic.

Do NOT ask the user to repeat context if it
already exists.

==================================================
QUESTION
==================================================

{question}

==================================================
ANSWER
==================================================

Provide a clear, structured educational answer.
"""

    # =====================================
    # ANSWER GENERATION (non-streaming)
    # =====================================
    # Kept as-is for any turn where OTHER intents are also requested
    # (notes/quiz/diagram/videos/papers/comparison alongside answer) —
    # orchestrator.run() still needs the complete string up front to
    # build memory_text and the combined response dict in one shot.

    @traceable(
        name="TutorAgent.generate_answer"
    )
    def generate_answer(
        self,
        question: str,
        context: str = "",
        history_text: str = "",
        summary: str = "",
        marks: str = None,
        strict_pdf: bool = False,
        pdf_searched: bool = False
    ):

        if marks is None:
            marks = self.detect_marks(question)

        if strict_pdf and not context.strip():

            return (
                "I couldn't find this in the selected PDF, so I "
                "can't answer it from the document."
            )

        prompt = self._build_prompt(
            question=question,
            context=context,
            history_text=history_text,
            summary=summary,
            marks=marks,
            strict_pdf=strict_pdf,
            pdf_searched=pdf_searched
        )

        try:

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="answer"
            )

            return response.strip()

        except LLMServiceError:

            # Provider failure — let the API report it instead of
            # returning a canned apology as if it were content.
            raise

        except Exception as e:

            print(
                f"TutorAgent Error: {e}"
            )

            return (
                "Sorry, I could not generate an answer."
            )

    # =====================================
    # ANSWER GENERATION (streaming)
    # =====================================
    # Used by Orchestrator.run_stream() ONLY for the simple case where
    # "answer" is the sole requested intent (no notes/quiz/diagram/
    # videos/papers/comparison alongside it) — that's the only case
    # where there's nothing else the response dict needs to wait on,
    # so streaming this text actually reduces perceived latency
    # instead of just reordering where the wait happens.

    def generate_answer_stream(
        self,
        question: str,
        context: str = "",
        history_text: str = "",
        summary: str = "",
        marks: str = None,
        strict_pdf: bool = False,
        pdf_searched: bool = False
    ):

        if marks is None:
            marks = self.detect_marks(question)

        if strict_pdf and not context.strip():

            def _empty_stream():
                yield (
                    "I couldn't find this in the selected PDF, so I "
                    "can't answer it from the document."
                )

            return _empty_stream()

        prompt = self._build_prompt(
            question=question,
            context=context,
            history_text=history_text,
            summary=summary,
            marks=marks,
            strict_pdf=strict_pdf,
            pdf_searched=pdf_searched
        )

        def _stream():

            try:

                for chunk in route_stream(
                    prompt=prompt,
                    provider=self.provider,
                    model=self.model,
                    purpose="answer"
                ):

                    yield chunk

            except LLMServiceError:

                # Provider failure — let the API report it instead of
                # returning a canned apology as if it were content.
                raise

            except Exception as e:

                print(f"TutorAgent stream error: {e}")

                yield "Sorry, I could not generate an answer."

        return _stream()