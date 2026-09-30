import json
import re

from langsmith import traceable
from models.errors import LLMQuotaExhaustedError
from models.router import route


class QueryResolverAgent:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    # Words that point back at earlier turns ("why is THAT needed?",
    # "draw IT", "explain the second ONE").
    _REFERENCE_RE = re.compile(
        r"\b(?:it|its|it's|this|that|these|those|they|them|their|he|she|"
        r"him|her|his|above|previous|previously|earlier|same|former|"
        r"latter|last one|second one|first one|the other)\b"
    )

    _FOLLOWUP_RE = re.compile(
        r"^(?:why|how|and|but|so|also|what about|how about|more|continue|"
        r"elaborate|explain (?:more|again|simply|further)|example|examples|"
        r"advantages|disadvantages|go on|then)\b"
    )

    @classmethod
    def needs_resolution(cls, query: str, has_history: bool) -> bool:
        """
        Whether the query depends on earlier turns and must be rewritten
        into a standalone question. No history -> never. Otherwise only
        when it refers back ("it", "that", ...) or is a short follow-up
        ("why?", "and TCP?", "examples"). A self-contained question skips
        the rewrite (and its LLM call) entirely.
        """

        if not has_history:
            return False

        q = query.lower().strip()

        if cls._REFERENCE_RE.search(q):
            return True

        return len(q.split()) <= 4 and bool(cls._FOLLOWUP_RE.search(q) or len(q.split()) <= 2)

    @traceable(
        name="QueryResolverAgent.resolve"
    )
    def resolve(
        self,
        query: str,
        history_text: str = "",
        summary: str = ""
    ):

        prompt = f"""
You are a conversational query resolver.

Your job:

1. Determine whether the user query is a follow-up.
2. Identify the actual topic.
3. Rewrite the query into a complete standalone query.

==================================================
CONVERSATION SUMMARY
==================================================

{summary}

==================================================
CONVERSATION HISTORY
==================================================

{history_text}

==================================================
CURRENT USER QUERY
==================================================

{query}

==================================================
OUTPUT FORMAT (JSON ONLY)
==================================================

{{
    "is_followup": true,
    "resolved_topic": "...",
    "resolved_query": "..."
}}

RULES:

- If the query depends on previous context,
  set is_followup=true.

- If the query is standalone,
  set is_followup=false.

- resolved_query must always be a complete,
  retrieval-friendly query.

Examples:

Query:
advantages?

Output:
{{
    "is_followup": true,
    "resolved_topic": "CNN",
    "resolved_query": "Advantages of CNN"
}}

Query:
draw it

Output:
{{
    "is_followup": true,
    "resolved_topic": "Superheterodyne Receiver",
    "resolved_query": "Block diagram of Superheterodyne Receiver"
}}

Query:
What is Gradient Descent?

Output:
{{
    "is_followup": false,
    "resolved_topic": "Gradient Descent",
    "resolved_query": "What is Gradient Descent?"
}}

Return ONLY JSON.
"""

        fallback = {
            "is_followup": False,
            "resolved_topic": query,
            "resolved_query": query
        }

        try:

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="resolve"
            )

            if not response or not response.strip():

                # route() sometimes returns an empty string (rate
                # limit, safety filter, transient provider hiccup).
                # json.loads("") raises "Expecting value: line 1
                # column 1 (char 0)" — the exact error this was
                # producing on every occurrence. Fail fast into the
                # fallback instead of letting json.loads blow up.
                print(
                    "QueryResolver Error: model returned an empty "
                    "response."
                )

                return fallback

            cleaned = response.strip()

            # Strip markdown code fences if the model adds them
            # despite being told "Return ONLY JSON" — same pattern
            # already used in IntentClassifier.
            cleaned = cleaned.replace("```json", "")
            cleaned = cleaned.replace("```", "")
            cleaned = cleaned.strip()

            try:

                result = json.loads(cleaned)

            except json.JSONDecodeError:

                # Last resort: some models prepend a sentence of
                # preamble before the JSON object even when told not
                # to. Try to pull out the first {...} block instead
                # of giving up entirely.
                match = re.search(r"\{.*\}", cleaned, re.DOTALL)

                if not match:
                    raise

                result = json.loads(match.group(0))

            # Make sure all expected keys are present even if the
            # model omitted one — callers (Orchestrator) read these
            # with .get() defaults, but keeping the shape consistent
            # here avoids surprises.
            fallback.update(result)

            return fallback

        except LLMQuotaExhaustedError:

            # Daily quota: the rest of this turn can't succeed either —
            # fail now instead of falling back and calling again.
            raise

        except Exception as e:

            print(
                f"QueryResolver Error: {e}"
            )

            return fallback