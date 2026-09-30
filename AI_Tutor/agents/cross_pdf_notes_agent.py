from langsmith import traceable

from models.router import route
from models.errors import LLMServiceError


class CrossPDFNotesAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):

        self.provider = provider
        self.model = model

    @traceable(
        name="CrossPDFNotesAgent.generate_notes"
    )
    def generate_notes(
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
Generate consolidated study notes.

Topic:
{topic}

PDF Content:

{pdf_text}

Instructions:

1. Combine information from all PDFs.
2. Remove duplicate information.
3. Mention unique ideas from each PDF.
4. Create exam-oriented notes.
5. Use headings and bullet points.

Output Format:

# Definition

# Key Concepts

# Important Points

# Advantages

# Disadvantages

# Applications

# Exam Notes

# Quick Revision
"""

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
                f"CrossPDFNotesAgent Error: {e}"
            )

            return (
                "Unable to generate notes."
            )