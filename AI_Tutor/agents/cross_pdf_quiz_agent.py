from langsmith import traceable

from models.router import route
from models.errors import LLMServiceError


class CrossPDFQuizAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):

        self.provider = provider
        self.model = model

    @traceable(
        name="CrossPDFQuizAgent.generate_quiz"
    )
    def generate_quiz(
        self,
        topic: str,
        pdf_contexts: dict
    ):

        try:

            if not pdf_contexts:

                return (
                    "No PDF content available."
                )

            pdf_text = ""

            for pdf_name, context in (
                pdf_contexts.items()
            ):

                pdf_text += f"""

PDF: {pdf_name}

{context}

=================================
"""

            prompt = f"""
Generate a comprehensive quiz.

Topic:
{topic}

PDF Content:

{pdf_text}

Instructions:

Create:

1. 5 MCQs
2. 5 Short Questions
3. 3 Long Questions
4. 2 Application-Based Questions

Use information from ALL PDFs.

Mix concepts across PDFs whenever possible.

Provide answers at the end.
"""

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
                f"CrossPDFQuizAgent Error: {e}"
            )

            return (
                "Unable to generate quiz."
            )