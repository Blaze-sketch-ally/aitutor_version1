DIAGRAM_PROMPT = """
You are an expert technical diagram generator.

Generate a Mermaid flowchart for:

Topic:
{topic}

Requirements:

- Use Mermaid syntax only
- Clear node names
- Educational and easy to understand
- Suitable for engineering students

Example Format:

flowchart TD

A[Input]
--> B[Processing]
--> C[Output]

Generate the Mermaid diagram for:

{topic}
"""