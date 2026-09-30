from langsmith import traceable
from models.router import route

class KnowledgeRouter:


    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    @traceable(name="KnowledgeRouter.route")
    def route_query(
        self,
        query: str
    ) -> str:
        """
        Returns:

        PDF_ONLY
        GENERAL_ONLY
        HYBRID
        """

        prompt = f"""
    ```

    You are a Knowledge Routing Agent.

    Your task is to determine how the answer should use
    uploaded PDF content.

    ---

    ## PDF_ONLY

    Choose PDF_ONLY ONLY if the user explicitly asks
    for information from the uploaded PDF.

    Examples:

    * According to the PDF...
    * From the uploaded document...
    * What does the PDF say?
    * Summarize the PDF
    * Explain chapter 2 from the PDF
    * Give notes from the uploaded file
    * What is written in the document?
    * Explain this PDF

    ---

    ## HYBRID

    Choose HYBRID if the user wants both:

    1. Information from the PDF

    AND

    2. Additional explanation or external knowledge.

    Examples:

    * Explain the PDF topic with examples
    * Expand the uploaded notes
    * Compare the PDF explanation with real applications
    * Explain the document and add more details
    * Use the PDF and your own knowledge

    ---

    ## GENERAL_ONLY

    Choose GENERAL_ONLY if:

    * User asks a normal question.
    * User does NOT explicitly mention PDF.
    * User wants videos.
    * User wants research papers.
    * User wants general AI knowledge.

    Examples:

    * What is Machine Learning?
    * Explain CNN
    * Give YouTube videos on Transformers
    * Research papers on RAG
    * Tell me about Python

    IMPORTANT:

    Do NOT assume the user wants PDF content
    just because a PDF exists.

    Return ONLY ONE of:

    PDF_ONLY

    GENERAL_ONLY

    HYBRID

    User Query:
    {query}

    Output:
    """


        try:

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="classify"
            )

            response = (
                response
                .strip()
                .upper()
            )

            print(
                f"Knowledge Route: {response}"
            )

            if "PDF_ONLY" in response:
                return "PDF_ONLY"

            elif "HYBRID" in response:
                return "HYBRID"

            else:
                return "GENERAL_ONLY"

        except Exception as e:

            print(
                f"Knowledge Router Error: {e}"
            )

            return "GENERAL_ONLY"

