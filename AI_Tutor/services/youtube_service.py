import os
import re

from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()


# =====================================
# DURATION PARSING
# =====================================
# YouTube returns duration as ISO 8601, e.g. "PT14M32S", "PT1H2M", "PT45S".
# No extra dependency needed for something this small.

_DURATION_RE = re.compile(
    r"PT"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?"
)


def parse_iso8601_duration(duration: str) -> int:
    """Returns total seconds. Returns 0 if it can't parse."""

    if not duration:
        return 0

    match = _DURATION_RE.match(duration)

    if not match:
        return 0

    parts = match.groupdict()

    hours = int(parts["hours"] or 0)
    minutes = int(parts["minutes"] or 0)
    seconds = int(parts["seconds"] or 0)

    return hours * 3600 + minutes * 60 + seconds


class YouTubeService:

    # Videos below this view count are excluded from ranking by
    # engagement — a handful of views with a few likes isn't a
    # meaningful signal and would otherwise dominate the ranking.
    MIN_VIEWS_FOR_RANKING = 500

    def __init__(self):
        self.api_key = os.getenv("YOUTUBE_API_KEY")

        self.youtube = build(
            "youtube",
            "v3",
            developerKey=self.api_key
        )

    # =====================================
    # SEARCH (unchanged behavior, just returns video_id separately
    # so callers can enrich without re-parsing the URL)
    # =====================================

    def search_videos(self, query: str, max_results: int = 5):

        request = self.youtube.search().list(
            q=query,
            part="snippet",
            type="video",
            maxResults=max_results
        )

        response = request.execute()

        videos = []

        for item in response.get("items", []):

            video_id = item["id"]["videoId"]
            snippet = item["snippet"]

            videos.append({
                "video_id": video_id,
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "description": snippet.get("description", ""),
                "published_at": snippet["publishedAt"],
                "thumbnail": snippet["thumbnails"]["high"]["url"],
                "url": f"https://www.youtube.com/watch?v={video_id}"
            })

        return videos

    # =====================================
    # ENRICH WITH STATS + DURATION
    # =====================================
    # search.list doesn't return view/like counts or duration — those
    # only come from videos.list. Batched in groups of 50 (the API's
    # per-request limit) even though in practice we'll rarely pass
    # more than ~15-20 ids at a time.

    def get_video_details(self, video_ids: list[str]) -> dict:

        details = {}

        for i in range(0, len(video_ids), 50):

            batch = video_ids[i:i + 50]

            request = self.youtube.videos().list(
                part="statistics,contentDetails",
                id=",".join(batch)
            )

            response = request.execute()

            for item in response.get("items", []):

                stats = item.get("statistics", {})
                content = item.get("contentDetails", {})

                view_count = int(stats.get("viewCount", 0) or 0)

                # likeCount is sometimes absent (creator hid it publicly)
                like_count = (
                    int(stats["likeCount"])
                    if "likeCount" in stats
                    else None
                )

                duration_seconds = parse_iso8601_duration(
                    content.get("duration", "")
                )

                details[item["id"]] = {
                    "views": view_count,
                    "likes": like_count,
                    "duration_seconds": duration_seconds
                }

        return details

    # =====================================
    # SEARCH + ENRICH + RANK
    # =====================================

    def search_and_rank(
        self,
        query: str,
        max_results: int = 5,
        candidate_pool: int = 15,
        duration_preference: str = "longest"
    ):
        """
        Pulls a larger candidate pool than max_results, enriches each
        with stats + duration, then sorts primarily by DURATION —
        longest first by default, or shortest first if
        duration_preference="shortest" — with engagement (like/view
        ratio, view-floored so low-view videos can't game it) only
        used to break ties between videos of equal length.

        duration_preference: "longest" | "shortest"
        """

        candidates = self.search_videos(
            query,
            max_results=candidate_pool
        )

        if not candidates:
            return []

        video_ids = [v["video_id"] for v in candidates]
        details = self.get_video_details(video_ids)

        for video in candidates:

            info = details.get(video["video_id"], {})

            views = info.get("views", 0)
            likes = info.get("likes")
            duration_seconds = info.get("duration_seconds", 0)

            video["views"] = views
            video["likes"] = likes
            video["duration_seconds"] = duration_seconds
            video["duration_minutes"] = round(duration_seconds / 60, 1)

            if likes is not None and views >= self.MIN_VIEWS_FOR_RANKING:
                video["score"] = likes / views
            else:
                video["score"] = 0.0

        longest_first = (duration_preference != "shortest")

        if longest_first:
            # Longer videos first; among equal-length videos, higher
            # engagement first.
            candidates.sort(
                key=lambda v: (v["duration_seconds"], v["score"]),
                reverse=True
            )
        else:
            # Shorter videos first; among equal-length videos, higher
            # engagement still wins (so it's not just "shortest and
            # lowest quality first").
            candidates.sort(
                key=lambda v: (-v["duration_seconds"], v["score"]),
                reverse=True
            )

        return candidates[:max_results]