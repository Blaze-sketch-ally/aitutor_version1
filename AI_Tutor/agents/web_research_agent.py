from langsmith import traceable

from services.tavily_service import TavilyService
from models.router import route


# Keyword heuristic for "does this need the news tool or the general web
# tool". Simple and cheap, same efficiency choice as youtube_agent.py's
# _detect_duration_preference — no extra LLM call just to pick a tool,
# since IntentClassifier's own web_research override already did the
# expensive part (deciding this request needs live web data at all).
_NEWS_HINTS = (
    "news", "breaking", "headline", "headlines", "today", "this week",
    "current events", "latest development", "latest developments",
    "happening now", "what's happening", "whats happening"
)


def _classify_tool(query: str) -> str:

    text = query.lower()

    if any(hint in text for hint in _NEWS_HINTS):
        return "news"

    return "general"


class WebResearchAgent:

    def __init__(self):

        self.tavily = TavilyService()

    # ----------------------------------
    # TOOLS
    # ----------------------------------

    @traceable(name="WebResearchAgent.news_search_tool")
    def news_search_tool(self, topic: str, max_results: int = 5):

        return self.tavily.search(
            topic,
            topic="news",
            max_results=max_results,
            days=14
        )

    @traceable(name="WebResearchAgent.web_search_tool")
    def web_search_tool(self, topic: str, max_results: int = 5):

        return self.tavily.search(
            topic,
            topic="general",
            max_results=max_results
        )

    # ----------------------------------
    # MAIN ENTRY POINT
    # ----------------------------------

    @traceable(name="WebResearchAgent.research")
    def research(
        self,
        query: str,
        history_text: str = "",
        summary: str = "",
        max_results: int = 5
    ):

        try:

            topic_prompt = f"""
Use conversation summary and history
to determine the actual topic to research.

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

Return ONLY the resolved topic to search for.
"""

            resolved_topic = route(
                prompt=topic_prompt,
                purpose="extract"
            ).strip()

            tool = _classify_tool(query)

            if tool == "news":
                results = self.news_search_tool(
                    resolved_topic,
                    max_results=max_results
                )
            else:
                results = self.web_search_tool(
                    resolved_topic,
                    max_results=max_results
                )

            if not results:

                return {
                    "answer": "",
                    "results": []
                }

            snippets_text = "\n\n".join(
                f"Source: {r['domain']}"
                + (f" ({r['published_date']})" if r.get("published_date") else "")
                + f"\nTitle: {r['title']}\n{r['snippet']}"
                for r in results
            )

            synthesis_prompt = f"""
You are an AI tutor answering a question using live web search results.

Write a concise, well-organized answer to the user's request using ONLY
the information in the search results below. Do not invent facts beyond
what the sources say. Do not include a numbered reference list or
citation markers in the text — the sources are already shown separately
to the user as cards, so just write a clean, readable answer.

==================================================
SEARCH RESULTS
==================================================

{snippets_text}

==================================================
USER REQUEST
==================================================

{query}

ANSWER:
"""

            answer = route(
                prompt=synthesis_prompt,
                purpose="answer"
            ).strip()

            return {
                "answer": answer,
                "results": results
            }

        except Exception as e:

            print(
                f"WebResearchAgent Error: {e}"
            )

            return {
                "answer": "",
                "results": []
            }
