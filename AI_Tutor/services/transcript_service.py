import re

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable
)


_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in",
    "on", "for", "and", "or", "what", "how", "why", "does", "do",
    "explain", "give", "me", "about", "with", "this", "that", "it",
    "as", "at", "by", "from", "be", "can", "you", "please", "tell"
}


def _significant_words(text: str) -> set:

    words = re.findall(r"[a-z0-9]+", text.lower())

    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _format_timestamp(seconds: float) -> str:

    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


class TranscriptService:

    # Merge caption entries into windows of roughly this length before
    # scoring, so we return a study-able chunk rather than one caption
    # line at a time.
    WINDOW_SECONDS = 45

    def get_transcript(self, video_id: str):
        """
        Returns a list of {"text": str, "start": float, "duration": float}
        or None if no transcript is available (captions disabled,
        video unavailable, etc.) — callers should treat None as
        "skip this feature for this video", not an error.

        youtube-transcript-api has changed its public API shape
        across major versions (list_transcripts as an instance method
        vs a classmethod vs removed entirely in favor of .fetch()).
        Rather than pin to one shape and break on whatever version
        ends up installed, this tries the modern API first and falls
        back to the older one.
        """

        # ---- Attempt 1: modern API (>= 1.0) ----
        # ytt_api.fetch(video_id, languages=[...]) -> FetchedTranscript
        # with a .snippets list of objects/dicts exposing text/start/duration.
        try:

            api = YouTubeTranscriptApi()

            fetched = api.fetch(video_id, languages=["en"])

            snippets = getattr(fetched, "snippets", fetched)

            entries = []

            for s in snippets:

                if isinstance(s, dict):
                    entries.append({
                        "text": s.get("text", ""),
                        "start": s.get("start", 0.0),
                        "duration": s.get("duration", 0.0)
                    })
                else:
                    entries.append({
                        "text": getattr(s, "text", ""),
                        "start": getattr(s, "start", 0.0),
                        "duration": getattr(s, "duration", 0.0)
                    })

            if entries:
                return entries

        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            return None
        except AttributeError:
            # This version doesn't have .fetch() on the instance —
            # fall through to the legacy API attempt below.
            pass
        except Exception as e:
            print(f"TranscriptService Error (modern API, {video_id}): {e}")
            # Fall through and try the legacy shape too, in case this
            # was e.g. a language-arg mismatch rather than a real
            # transcript-unavailable error.

        # ---- Attempt 2: legacy API (< 1.0) ----
        # Older versions expose this as a CLASSMETHOD (called on the
        # class itself, not an instance) — YouTubeTranscriptApi.get_transcript(...)
        try:

            raw_entries = YouTubeTranscriptApi.get_transcript(
                video_id,
                languages=["en"]
            )

            return [
                {
                    "text": e.get("text", ""),
                    "start": e.get("start", 0.0),
                    "duration": e.get("duration", 0.0)
                }
                for e in raw_entries
            ]

        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            return None
        except Exception as e:
            print(f"TranscriptService Error (legacy API, {video_id}): {e}")
            return None

    def find_best_segment(self, transcript_entries, query: str):
        """
        Merges transcript entries into fixed-length windows, scores
        each window by keyword overlap with the query, and returns
        the best-matching window as:
            {
                "start_seconds": float,
                "end_seconds": float,
                "start_label": "4:32",
                "end_label": "7:10",
                "snippet": "<window text, truncated>"
            }
        or None if there's nothing to match against.
        """

        if not transcript_entries:
            return None

        query_words = _significant_words(query)

        if not query_words:
            return None

        windows = []
        current_start = transcript_entries[0]["start"]
        current_text = []
        current_end = current_start

        for entry in transcript_entries:

            if entry["start"] - current_start > self.WINDOW_SECONDS and current_text:

                windows.append({
                    "start": current_start,
                    "end": current_end,
                    "text": " ".join(current_text)
                })

                current_start = entry["start"]
                current_text = []

            current_text.append(entry["text"])
            current_end = entry["start"] + entry.get("duration", 0)

        if current_text:
            windows.append({
                "start": current_start,
                "end": current_end,
                "text": " ".join(current_text)
            })

        best_window = None
        best_score = -1

        for window in windows:

            window_words = _significant_words(window["text"])

            if not window_words:
                continue

            overlap = len(query_words & window_words)

            # Normalize a little so a long, generic window doesn't win
            # purely on word count.
            score = overlap / (len(query_words) ** 0.5)

            if score > best_score:
                best_score = score
                best_window = window

        if best_window is None or best_score <= 0:
            return None

        snippet = best_window["text"].strip()
        if len(snippet) > 300:
            snippet = snippet[:300].rsplit(" ", 1)[0] + "..."

        return {
            "start_seconds": round(best_window["start"]),
            "end_seconds": round(best_window["end"]),
            "start_label": _format_timestamp(best_window["start"]),
            "end_label": _format_timestamp(best_window["end"]),
            "snippet": snippet
        }