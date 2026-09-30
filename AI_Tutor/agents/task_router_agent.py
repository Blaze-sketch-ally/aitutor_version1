from langsmith import traceable

from services.external_service_resolver import ExternalServiceResolver
from models.router import route


class TaskRouterAgent:
    """
    Handles requests that need an external website or service rather
    than an answer the tutor can generate itself — "where can I apply
    for X", "book me a flight", "register for Y certification". Never
    claims to have performed the action; only resolves and returns a
    verified destination for the user to complete it themselves.
    """

    def __init__(self):

        self.resolver = ExternalServiceResolver()

    @traceable(name="TaskRouterAgent.registry_lookup")
    def _check_registry(self, query: str, resolved_topic: str):

        return self.resolver.check_registry(query, resolved_topic)

    @traceable(name="TaskRouterAgent.tavily_fallback")
    def _tavily_fallback(self, resolved_topic: str):

        return self.resolver.search_and_verify(resolved_topic)

    @traceable(name="TaskRouterAgent.route_task")
    def route_task(
        self,
        query: str,
        history_text: str = "",
        summary: str = ""
    ):

        try:

            topic_prompt = f"""
Use conversation summary and history to determine what external
service, website, or task the user actually needs.

==================================================
CONVERSATION SUMMARY
==================================================

{summary}

==================================================
CONVERSATION HISTORY
==================================================

{history_text}

==================================================
CURRENT REQUEST
==================================================

{query}

Return ONLY the resolved service/task name to look up (e.g.
"AWS certification", "passport application", "flight booking Kolkata
to Delhi").
"""

            resolved_topic = route(
                prompt=topic_prompt,
                purpose="extract"
            ).strip()

            action = self._check_registry(query, resolved_topic)

            if not action:
                action = self._tavily_fallback(resolved_topic)

            if not action:

                return {
                    "message": None,
                    "action": None
                }

            message_prompt = f"""
You are an AI tutor. The user's request needs an external website or
service — you are NOT able to perform this action yourself. You cannot
submit forms, book anything, register anything, purchase anything,
apply for anything, or log into any account on the user's behalf.

Write ONE short, honest message (1-2 sentences) telling the user where
they can complete this themselves.

HARD RULES:
- NEVER say or imply that you completed, submitted, booked, registered,
  purchased, applied for, or otherwise finished the action.
- If the user's request was phrased as a command ("book me a flight",
  "apply for me"), make clear you can't do it directly before pointing
  them to where they can.
- NEVER invent details about the service beyond what's given below.
- Do NOT include the raw URL in your message — a button with the link
  is shown separately, right under your message.
- Keep it to 1-2 sentences, plain text, no markdown.

SERVICE: {action['service']}
SOURCE TYPE: {action['source_type']}

USER REQUEST: {query}

MESSAGE:
"""

            message = route(
                prompt=message_prompt,
                purpose="chat"
            ).strip()

            return {
                "message": message,
                "action": action
            }

        except Exception as e:

            print(
                f"TaskRouterAgent Error: {e}"
            )

            return {
                "message": None,
                "action": None
            }
