from models.router import route


class DiagramService:

    def generate_mermaid(
        self,
        topic: str
    ):

        prompt = f"""
Generate a Mermaid flowchart for:

{topic}

Rules:
- Return ONLY Mermaid code
- No explanations
"""

        return route(prompt)