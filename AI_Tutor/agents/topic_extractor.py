from langsmith import traceable
from models.router import route


class TopicExtractor:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    @traceable(
        name="TopicExtractor.extract_topics"
    )
    def extract_topics(
        self,
        context: str
    ):

        if not context or not context.strip():

            return []

        prompt = f"""
You are an expert academic topic extraction system.

Your task:

Extract the MOST IMPORTANT technical concepts,
topics, algorithms, methods, frameworks,
technologies or keywords from the text.

RULES:

- Return ONLY topic names.
- One topic per line.
- No numbering.
- No bullets.
- No explanations.
- No headings.
- No extra text.

GOOD EXAMPLE:

Convolutional Neural Networks
Backpropagation
Gradient Descent
Image Classification
Feature Extraction

BAD EXAMPLE:

1. Convolutional Neural Networks
2. Gradient Descent

OR

The important topics are:
CNN
Gradient Descent

TEXT:

{context}

OUTPUT:
"""

        try:

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="extract"
            )

            topics = []

            for line in response.split("\n"):

                topic = line.strip()

                if not topic:
                    continue

                topic = topic.replace("-", "")
                topic = topic.replace("*", "")

                topic = topic.strip()

                if len(topic) < 3:
                    continue

                topics.append(topic)

            # Remove duplicates while preserving order
            unique_topics = []

            seen = set()

            for topic in topics:

                key = topic.lower()

                if key not in seen:

                    unique_topics.append(topic)

                    seen.add(key)

            return unique_topics[:5]

        except Exception as e:

            print(
                f"TopicExtractor Error: {e}"
            )

            return []