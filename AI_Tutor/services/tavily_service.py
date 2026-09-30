import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()


def _domain(url: str) -> str:

    try:
        netloc = urlparse(url).netloc
        return netloc.replace("www.", "") if netloc else url
    except Exception:
        return url


class TavilyService:
    """
    Thin wrapper around the Tavily search API. Two "topics" on the same
    client cover both required tools: topic="general" for broad/recent
    web information, topic="news" for current events with day-bounded
    recency filtering.

    Same division of responsibility as youtube_service.py /
    services/arxiv.py: this class does the raw external-API call and
    normalizes the response shape. It does NOT catch exceptions itself
    — that's the calling agent's job (WebResearchAgent), matching the
    rest of the codebase's service/agent split.
    """

    def __init__(self):
        self.client = TavilyClient(
            api_key=os.getenv("TAVILY_API_KEY")
        )

    def search(
        self,
        query: str,
        topic: str = "general",
        max_results: int = 5,
        days: int | None = None
    ) -> list[dict]:

        params = {
            "query": query,
            "topic": topic,
            "max_results": max_results,
            "search_depth": "basic"
        }

        # days only means something for topic="news" — Tavily ignores it
        # otherwise, but only pass it when set so a "general" search
        # never accidentally gets time-boxed.
        if days is not None:
            params["days"] = days

        response = self.client.search(**params)

        results = []

        for item in response.get("results", []):

            url = item.get("url", "")

            results.append({
                "title": item.get("title", "Untitled"),
                "url": url,
                "snippet": item.get("content", ""),
                "domain": _domain(url),
                "published_date": item.get("published_date"),
                "tool": topic
            })

        return results
