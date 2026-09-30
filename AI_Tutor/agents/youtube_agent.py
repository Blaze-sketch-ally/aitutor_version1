from langsmith import traceable

from services.youtube_service import (
    YouTubeService
)

from services.transcript_service import (
    TranscriptService
)

from agents.topic_extractor import (
    TopicExtractor
)

from models.router import route


# Keyword heuristic for "did the user ask for shorter/longer videos".
# Simple and cheap; if you want this to be more reliable, route it
# through the LLM intent classifier instead (same pattern as
# resolved_topic below) rather than expanding this list indefinitely.
_SHORT_HINTS = (
    "short", "shorter", "shortest", "quick", "quickly", "brief",
    "briefly", "small", "concise", "fast", "summary"
)
_LONG_HINTS = (
    "long", "longer", "longest", "detailed", "in-depth", "in depth",
    "full", "comprehensive", "complete", "deep dive", "lecture"
)


def _detect_duration_preference(query: str) -> str:

    text = query.lower()

    if any(hint in text for hint in _SHORT_HINTS):
        return "shortest"

    if any(hint in text for hint in _LONG_HINTS):
        return "longest"

    # Default per product decision: longest first unless the user
    # signals otherwise.
    return "longest"


class YouTubeAgent:

    def __init__(self):

        self.youtube_service = (
            YouTubeService()
        )

        self.transcript_service = (
            TranscriptService()
        )

        self.topic_extractor = (
            TopicExtractor()
        )

    @traceable(name="YouTubeAgent.search_videos")
    def get_videos(
        self,
        query: str,
        context: str = "",
        history_text: str = "",
        summary: str = "",
        max_results: int = 5
    ):

        try:

            duration_preference = _detect_duration_preference(query)

            topic_prompt = f"""
Use conversation summary and history
to determine the actual topic.

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

            videos = []
            seen = set()

            if context.strip():

                try:

                    topics = (
                        self.topic_extractor.extract_topics(
                            context
                        )
                    )

                except Exception:

                    topics = [resolved_topic]

                for topic in topics:

                    results = (
                        self.youtube_service.search_and_rank(
                            topic,
                            max_results=max_results,
                            duration_preference=duration_preference
                        )
                    )

                    for video in results:

                        key = video.get("url", "")

                        if key not in seen:

                            seen.add(key)
                            videos.append(video)

                # Re-sort the merged pool across topics using the same
                # duration-first rule, so combining multiple topics
                # doesn't undo the ordering.
                longest_first = (duration_preference != "shortest")

                if longest_first:
                    videos.sort(
                        key=lambda v: (
                            v.get("duration_seconds", 0),
                            v.get("score", 0)
                        ),
                        reverse=True
                    )
                else:
                    videos.sort(
                        key=lambda v: (
                            -v.get("duration_seconds", 0),
                            v.get("score", 0)
                        ),
                        reverse=True
                    )

                videos = videos[:max_results]

            else:

                videos = self.youtube_service.search_and_rank(
                    resolved_topic,
                    max_results=max_results,
                    duration_preference=duration_preference
                )

            # =====================================
            # ATTACH STUDY SEGMENT (best-match timestamp)
            # =====================================
            # Best-effort: if captions are disabled or the transcript
            # library fails for a given video, we just omit
            # study_segment for that one video rather than failing
            # the whole response.

            for video in videos:

                video["study_segment"] = None

                try:

                    transcript_entries = (
                        self.transcript_service.get_transcript(
                            video["video_id"]
                        )
                    )

                    if transcript_entries:

                        segment = (
                            self.transcript_service.find_best_segment(
                                transcript_entries,
                                query
                            )
                        )

                        if segment:

                            video["study_segment"] = segment

                            video["url_at_timestamp"] = (
                                f"{video['url']}&t="
                                f"{segment['start_seconds']}s"
                            )

                except Exception as e:

                    print(
                        f"YouTubeAgent transcript error "
                        f"({video.get('video_id')}): {e}"
                    )

            return videos

        except Exception as e:

            print(
                f"YouTubeAgent Error: {e}"
            )

            return []