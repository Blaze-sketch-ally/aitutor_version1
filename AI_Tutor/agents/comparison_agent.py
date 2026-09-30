from langsmith import traceable

from models.router import route
from models.errors import LLMServiceError


class ComparisonAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):

        self.provider = provider
        self.model = model

    @traceable(
        name="ComparisonAgent.generate_comparison"
    )
    def generate_comparison(
        self,
        topic: str,
        pdf_contexts: dict,
        history_text: str = "",
        summary: str = "",
        strict_pdf: bool = False,
        pdf_searched: bool = False,
        compare_documents: bool = False
    ):
        """
        Modes (chosen by Orchestrator's retrieval plan):

        - pdf_contexts empty, strict_pdf  -> the user asked for a
          comparison FROM the PDF and it has nothing relevant: say so,
          don't answer from general knowledge.
        - pdf_contexts empty otherwise    -> ordinary concept comparison
          from general knowledge ("Compare CNN and RNN"), noting when a
          selected PDF was searched and didn't cover it. This used to
          return "No PDF information available" for every comparison
          made without a PDF.
        - compare_documents               -> compare the PDFs themselves
          ("compare the two PDFs"): the per-PDF format below.
        - otherwise                       -> compare the concepts using
          the PDF evidence (strict = PDF only; else PDF first, general
          knowledge clearly labelled).
        """

        try:

            if not pdf_contexts:

                if strict_pdf:

                    return (
                        "I couldn't find information for this comparison "
                        "in the selected PDF, so I can't compare these "
                        "from the document."
                    )

                return self._general_comparison(
                    topic=topic,
                    history_text=history_text,
                    summary=summary,
                    pdf_searched=pdf_searched
                )

            if not compare_documents:

                return self._concept_comparison_from_pdf(
                    topic=topic,
                    pdf_contexts=pdf_contexts,
                    history_text=history_text,
                    summary=summary,
                    strict_pdf=strict_pdf
                )

            pdf_text = ""

            for pdf_name, context in (
                pdf_contexts.items()
            ):

                pdf_text += f"""

==================================================
PDF NAME: {pdf_name}
==================================================

{context}

"""

            prompt = f"""
You are an expert academic comparison tutor.

Your task is to compare information
across MULTIPLE PDFs.

Conversation Summary:
{summary}

Chat History:
{history_text}

User Request:
{topic}

PDF Contents:

{pdf_text}

Instructions:

1. Identify ALL PDFs involved.

2. For each PDF:
   - Explain its viewpoint
   - Explain its explanation
   - Explain its contribution

3. Compare the PDFs.

4. Highlight:
   - Similarities
   - Differences
   - Unique Ideas

5. If one PDF contains information
   that another PDF does not,
   explicitly mention it.

6. If only one PDF contains relevant
   information, clearly state that.

7. Create a comparison table.

8. Be detailed and educational.

Output Format:

# PDFs Involved

# Overview

# PDF-wise Explanation

## PDF 1
...

## PDF 2
...

## PDF 3
...

# Similarities

# Differences

# Comparison Table

| Feature | PDF 1 | PDF 2 | PDF 3 |

# Key Insights

# Final Summary
"""

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="comparison"
            )

            return response

        except LLMServiceError:

            # Provider failure — let the API report it instead of
            # returning a canned apology as if it were content.
            raise

        except Exception as e:

            print(
                f"ComparisonAgent Error: {e}"
            )

            return (
                "Unable to generate comparison."
            )

    # ----------------------------------
    # GENERAL-KNOWLEDGE COMPARISON
    # ----------------------------------

    def _general_comparison(
        self,
        topic: str,
        history_text: str,
        summary: str,
        pdf_searched: bool
    ) -> str:

        source_rule = (
            "The student has PDF material selected, but it contains "
            "nothing relevant to this comparison. Start with one short "
            "sentence saying the selected PDF doesn't cover this, so the "
            "comparison is from general knowledge. Never claim or imply "
            "that the PDF says anything."
            if pdf_searched else
            "Use your own knowledge."
        )

        prompt = f"""
You are an expert academic comparison tutor.

{source_rule}

Conversation Summary:
{summary}

Chat History:
{history_text}

User Request:
{topic}

Instructions:
- Briefly explain each concept being compared.
- Cover similarities, differences, strengths/weaknesses and typical
  use cases.
- Include a comparison table.
- If you are unsure about a detail, say so instead of guessing.

Output Format:

# Overview
# Similarities
# Differences
# Comparison Table
# When to Use Which
# Summary
"""

        return route(
            prompt=prompt,
            provider=self.provider,
            model=self.model,
            purpose="comparison"
        )

    # ----------------------------------
    # CONCEPT COMPARISON GROUNDED IN PDF
    # ----------------------------------

    def _concept_comparison_from_pdf(
        self,
        topic: str,
        pdf_contexts: dict,
        history_text: str,
        summary: str,
        strict_pdf: bool
    ) -> str:

        evidence = "\n\n".join(
            f"--- From {name} ---\n{text}"
            for name, text in pdf_contexts.items()
        )

        source_rule = (
            """Use ONLY the PDF evidence below.
- Do NOT use outside knowledge.
- If the evidence doesn't cover part of the comparison, say
  "The PDF does not say" for that part instead of filling it in."""
            if strict_pdf else
            """Use the PDF evidence below as the PRIMARY source.
- Only attribute to the PDF what the evidence actually says.
- You may add general knowledge, but mark it clearly as
  "(general knowledge, not from the PDF)"."""
        )

        prompt = f"""
You are an expert academic comparison tutor.

Compare the concepts in the user's request.

SOURCE RULES:
- {source_rule}

Conversation Summary (conversation only — NOT document evidence):
{summary}

Chat History (conversation only — NOT document evidence):
{history_text}

User Request:
{topic}

PDF EVIDENCE:
{evidence}

Output Format:

# Overview
# Similarities
# Differences
# Comparison Table
# Summary
"""

        return route(
            prompt=prompt,
            provider=self.provider,
            model=self.model,
            purpose="comparison"
        )