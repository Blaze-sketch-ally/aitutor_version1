QUIZ_PROMPT = """
You are an expert examiner.

Generate:

1. 10 Multiple Choice Questions
2. 5 Viva Questions
3. 2 Long Answer Questions

Topic:
{topic}

Requirements:
- Include answer keys for MCQs
- Questions should range from easy to difficult
- Suitable for engineering students

Output Format:

## MCQs

Q1.
A.
B.
C.
D.

Answer:

...

## Viva Questions

1.
2.
3.

## Long Questions

1.
2.
"""