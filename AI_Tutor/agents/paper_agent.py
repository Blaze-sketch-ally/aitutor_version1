import re

from langsmith import traceable
import arxiv

from agents.topic_extractor import TopicExtractor
from models.router import route


def _significant_words(text: str) -> set:

    words = re.findall(r"[a-z0-9]+", text.lower())

    return {w for w in words if len(w) > 2}


class PaperAgent:

    def __init__(
        self,
        max_results: int = 5
    ):
        self.max_results = max_results
        self.topic_extractor = TopicExtractor()

    def _search_arxiv(
        self,
        query: str
    ):

        papers = []

        search = arxiv.Search(
            query=query,
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )

        client = arxiv.Client()

        for result in client.results(search):

            papers.append(
                {
                    "title": result.title,
                    "summary": result.summary,
                    "authors": [
                        author.name
                        for author in result.authors
                    ],
                    "published": str(
                        result.published
                    ),
                    "pdf_url": result.pdf_url,
                    "entry_id": result.entry_id
                }
            )

        return papers

    @traceable(name="PaperAgent.search_papers")
    def get_papers(
        self,
        query: str,
        context: str = "",
        history_text: str = "",
        summary: str = ""
    ):

        try:

            topic_prompt = f"""
Use the conversation summary and history
to determine the real topic.

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

Return ONLY the resolved topic.
"""

            resolved_topic = route(
                prompt=topic_prompt,
                purpose="extract"
            ).strip()

            papers = []
            seen = set()

            # Always search the resolved topic — this is what the
            # user actually asked for and must never be silently
            # dropped. The old version, when context was present,
            # searched ONLY context-derived topics and returned
            # immediately — meaning stale/irrelevant PDF context
            # (or a completely unrelated PDF sitting in the session)
            # could silently replace the actual query topic. Same
            # bug class already fixed in YouTubeAgent; applying the
            # identical fix here.
            topics_to_search = [resolved_topic]

            if context.strip():

                try:

                    context_topics = (
                        self.topic_extractor.extract_topics(
                            context
                        )
                    )

                except Exception:

                    context_topics = []

                query_words = _significant_words(
                    resolved_topic + " " + query
                )

                overlapping = [
                    topic for topic in context_topics
                    if _significant_words(topic) & query_words
                ]

                if overlapping:

                    topics_to_search.extend(overlapping)

                elif context_topics:

                    # Nothing overlapped with the query at all —
                    # typically because resolved_topic itself carries
                    # no real topic (a meta-instruction like "give me
                    # papers on the pdf I uploaded"). In that case
                    # trust the PDF-derived topics entirely rather
                    # than returning nothing useful.
                    topics_to_search = context_topics

            for topic in topics_to_search:

                results = self._search_arxiv(
                    topic
                )

                for paper in results:

                    key = (
                        paper["title"]
                        .lower()
                        .strip()
                    )

                    if key not in seen:

                        seen.add(key)
                        papers.append(paper)

            return papers[:self.max_results]

        except Exception as e:

            print(
                f"PaperAgent Error: {e}"
            )

            return []