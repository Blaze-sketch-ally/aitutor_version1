import os
import re
import tempfile
import shutil

from urllib.parse import urlparse, parse_qs

from langsmith import traceable
from models.router import route


# ==================================================
# CONFIG
# ==================================================

# Groq's audio transcription endpoint has a per-request file size cap.
# Stay comfortably under it (check current limits in Groq's docs — this
# is intentionally conservative) so we chunk before Groq ever rejects
# the upload, rather than reacting to a 413 after the fact.
_MAX_AUDIO_BYTES = 24 * 1024 * 1024  # ~24 MB

# Length of each chunk when an audio file needs to be split.
_CHUNK_MS = 10 * 60 * 1000  # 10 minutes

# If the transcript is longer than this many characters, summarize it
# in a map-reduce pattern instead of one giant prompt (keeps well
# within context limits and avoids truncated/degraded summaries on
# long lecture-length videos, regardless of whether the transcript
# came from YouTube captions or Whisper).
_MAP_REDUCE_THRESHOLD_CHARS = 12000
_MAP_CHUNK_CHARS = 6000

_YOUTUBE_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
    r"[\w-]+"
)


def find_youtube_url(text: str) -> str | None:
    """
    Returns the first YouTube URL found in text, or None. Used by
    Orchestrator as a hard, regex-based detector — same philosophy as
    the other keyword overrides in this codebase — rather than relying
    on the LLM intent classifier to notice a link was pasted in.
    """

    match = _YOUTUBE_URL_PATTERN.search(text)

    if not match:
        return None

    url = match.group(0)

    if not url.startswith("http"):
        url = "https://" + url

    return url


def extract_video_id(url: str) -> str | None:
    """
    Pulls the 11-character video ID out of any common YouTube URL
    shape, correctly ignoring extra query params like a playlist
    "&list=..." tag that a user's pasted link might carry alongside
    "v=...". Using urlparse/parse_qs here (rather than a single regex)
    is what makes that robust — a naive regex on "v=" can otherwise
    grab the wrong parameter when a playlist ID is also present.
    """

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if host in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.lstrip("/").split("/")[0]
        return video_id or None

    if "youtube.com" in host:

        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            values = qs.get("v")
            return values[0] if values else None

        for prefix in ("/shorts/", "/embed/"):
            if parsed.path.startswith(prefix):
                remainder = parsed.path[len(prefix):]
                return remainder.split("/")[0] or None

    return None


class VideoSummaryAgent:

    def __init__(
        self,
        provider="groq",
        model=None,
        whisper_model="whisper-large-v3"
    ):
        self.provider = provider
        self.model = model
        self.whisper_model = whisper_model

    # ==================================================
    # PUBLIC ENTRY POINT
    # ==================================================

    @traceable(
        name="VideoSummaryAgent.summarize_video"
    )
    def summarize_video(
        self,
        youtube_url: str | None = None,
        uploaded_video_path: str | None = None,
        topic: str = "",
        history_text: str = "",
        summary: str = ""
    ) -> dict:
        """
        Returns a dict:
            {
                "source": "youtube" | "upload",
                "source_ref": "<url or filename>",
                "transcript_source": "captions" | "whisper" | None,
                "transcript": "<full transcript text>",
                "summary": "<LLM-generated summary>"
            }
        On failure, "summary" contains a user-facing error message and
        "transcript" is "".

        For YouTube links, this tries YouTube's own captions first
        (fast, free, no download) and only falls back to downloading
        audio + Groq Whisper transcription if no captions are
        available. This also sidesteps YouTube's bot-detection on
        server-side audio downloads for the common case where captions
        exist at all.
        """

        if not youtube_url and not uploaded_video_path:
            return {
                "source": None,
                "source_ref": None,
                "transcript_source": None,
                "transcript": "",
                "summary": (
                    "I didn't find a YouTube link or an uploaded video "
                    "to summarize."
                )
            }

        temp_dir = None

        try:

            if youtube_url:

                source = "youtube"
                source_ref = youtube_url
                transcript = None
                transcript_source = None

                video_id = extract_video_id(youtube_url)

                if video_id:
                    transcript = self._fetch_youtube_transcript(video_id)

                if transcript:

                    transcript_source = "captions"
                    print(
                        "VideoSummaryAgent: using YouTube captions "
                        "(no audio download needed)."
                    )

                else:

                    print(
                        "VideoSummaryAgent: no usable captions found — "
                        "falling back to audio download + Whisper."
                    )

                    temp_dir, audio_path = self._download_youtube_audio(
                        youtube_url
                    )
                    transcript = self._transcribe(audio_path)
                    transcript_source = "whisper" if transcript else None

            else:

                source = "upload"
                source_ref = os.path.basename(uploaded_video_path)
                transcript = self._transcribe(uploaded_video_path)
                transcript_source = "whisper" if transcript else None

            if not transcript or not transcript.strip():
                return {
                    "source": source,
                    "source_ref": source_ref,
                    "transcript_source": None,
                    "transcript": "",
                    "summary": (
                        "I couldn't get a transcript for this video — "
                        "it may have no captions and no clear speech "
                        "audio, or the audio track could not be read."
                    )
                }

            video_summary = self._summarize_transcript(
                transcript=transcript,
                topic=topic,
                history_text=history_text,
                summary=summary
            )

            return {
                "source": source,
                "source_ref": source_ref,
                "transcript_source": transcript_source,
                "transcript": transcript,
                "summary": video_summary
            }

        except Exception as e:

            print(f"VideoSummaryAgent error: {e}")

            return {
                "source": "youtube" if youtube_url else "upload",
                "source_ref": youtube_url or uploaded_video_path,
                "transcript_source": None,
                "transcript": "",
                "summary": (
                    "Sorry, I couldn't process this video right now. "
                    "This can happen if the link is private/unavailable, "
                    "the file format isn't supported, or the video is "
                    "too long to process."
                )
            }

        finally:

            # Clean up the temp directory used for downloaded YouTube
            # audio. Uploaded files are owned by the caller (app.py) —
            # we never delete those here.
            if temp_dir and os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ==================================================
    # STEP 1a — YOUTUBE CAPTIONS (preferred path)
    # ==================================================

    def _fetch_youtube_transcript(self, video_id: str) -> str | None:
        """
        Tries to fetch YouTube's own caption track for a video, in this
        priority order: manually-created English captions, then
        auto-generated English captions, then whatever's available in
        any language. Returns None (never raises) if nothing usable is
        found, so the caller can transparently fall back to Whisper.

        Handles both youtube-transcript-api API shapes, since this
        changed across major versions of the library:
          - >= 1.0: instance-based — YouTubeTranscriptApi().list(video_id)
          - <  1.0: classmethod-based — YouTubeTranscriptApi.list_transcripts(video_id)
        Whichever is installed, this tries the new style first and
        falls back to the old style, rather than assuming one or the
        other and breaking on whatever the user has installed.
        """

        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            print(
                "VideoSummaryAgent: youtube-transcript-api not installed "
                "— skipping captions, will fall back to Whisper. Run "
                "`pip install youtube-transcript-api` to enable this "
                "faster/free path."
            )
            return None

        transcript_list = None

        # Newer API (>= 1.0): instance-based.
        try:
            transcript_list = YouTubeTranscriptApi().list(video_id)
        except AttributeError:
            transcript_list = None
        except Exception as e:
            print(f"VideoSummaryAgent: instance-based caption list failed: {e}")
            transcript_list = None

        # Older API (< 1.0): classmethod-based.
        if transcript_list is None:
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            except Exception as e:
                print(f"VideoSummaryAgent: no caption list available: {e}")
                return None

        transcript_obj = None

        try:
            transcript_obj = transcript_list.find_manually_created_transcript(
                ["en"]
            )
        except Exception:
            pass

        if transcript_obj is None:
            try:
                transcript_obj = transcript_list.find_generated_transcript(
                    ["en"]
                )
            except Exception:
                pass

        if transcript_obj is None:
            try:
                # Last resort: grab whatever language/track is available.
                for candidate in transcript_list:
                    transcript_obj = candidate
                    break
            except Exception:
                pass

        if transcript_obj is None:
            return None

        try:
            segments = transcript_obj.fetch()
        except Exception as e:
            print(f"VideoSummaryAgent: caption fetch failed: {e}")
            return None

        # Newer API returns an iterable of snippet OBJECTS (with a
        # .text attribute); older API returns an iterable of plain
        # dicts (with a "text" key). Handle both without assuming
        # which one is installed.
        texts = []
        for seg in segments:
            if isinstance(seg, dict):
                t = seg.get("text", "")
            else:
                t = getattr(seg, "text", "")
            if t and t.strip():
                texts.append(t.strip())

        return " ".join(texts).strip() or None

    # ==================================================
    # STEP 1b — GET AUDIO (YouTube download, fallback only)
    # ==================================================

    def _download_youtube_audio(self, url: str) -> tuple[str, str]:
        """
        Downloads the best available audio track for a YouTube video
        and converts it to mp3 via yt-dlp + ffmpeg. Requires ffmpeg to
        be installed and on PATH.

        Only called when no captions are available — YouTube's
        bot-detection on server-side downloads means this path is
        noticeably less reliable than captions, which is why captions
        are tried first in summarize_video().

        Returns (temp_dir, audio_file_path) — caller is responsible
        for cleaning up temp_dir once done.
        """

        import yt_dlp

        temp_dir = tempfile.mkdtemp(prefix="video_summary_")
        out_template = os.path.join(temp_dir, "%(id)s.%(ext)s")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id")

        audio_path = os.path.join(temp_dir, f"{video_id}.mp3")

        if not os.path.exists(audio_path):
            raise RuntimeError(
                "yt-dlp did not produce an audio file — the video may "
                "be unavailable, age-restricted, region-locked, or "
                "blocked by YouTube's bot-detection for server-side "
                "downloads."
            )

        return temp_dir, audio_path

    # ==================================================
    # STEP 2 — TRANSCRIBE (Groq Whisper API)
    # ==================================================

    def _get_groq_client(self):

        from groq import Groq

        # Same key accessor as every other Groq client (canonical env var
        # GROQ_APIKEY, deprecated fallback GROQ_API_KEY — see
        # models/config.py).
        from models.config import CANONICAL_GROQ_KEY_VAR, get_groq_api_key

        api_key = get_groq_api_key()

        if not api_key:
            raise RuntimeError(
                f"{CANONICAL_GROQ_KEY_VAR} environment variable is not set — "
                "required for audio transcription."
            )

        return Groq(api_key=api_key)

    def _transcribe(self, audio_path: str) -> str:
        """
        Transcribes a single audio/video file via Groq Whisper,
        transparently chunking it first if it's larger than Groq's
        per-request size limit. This is the fallback path used when no
        YouTube captions exist, and the only path for uploaded files.
        """

        if os.path.getsize(audio_path) > _MAX_AUDIO_BYTES:

            chunk_paths = self._chunk_audio(audio_path)

            try:
                transcripts = [
                    self._transcribe_single(p) for p in chunk_paths
                ]
                return " ".join(t.strip() for t in transcripts if t.strip())
            finally:
                for p in chunk_paths:
                    try:
                        os.remove(p)
                    except OSError:
                        pass

        return self._transcribe_single(audio_path)

    def _transcribe_single(self, audio_path: str) -> str:

        client = self._get_groq_client()

        with open(audio_path, "rb") as f:

            result = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model=self.whisper_model,
                response_format="text"
            )

        # Groq's SDK returns a plain str when response_format="text",
        # but guard for SDK versions that wrap it in an object.
        return result if isinstance(result, str) else getattr(
            result, "text", str(result)
        )

    def _chunk_audio(self, audio_path: str) -> list:
        """
        Splits an oversized audio file into <= _CHUNK_MS segments using
        pydub (requires ffmpeg on PATH). Returns a list of temp chunk
        file paths — caller is responsible for deleting them. This is
        what makes a very long/large uploaded video (or a long video
        that fell back to Whisper) processable instead of just
        rejected by Groq's size limit.
        """

        from pydub import AudioSegment

        audio = AudioSegment.from_file(audio_path)

        chunk_paths = []

        for i, start_ms in enumerate(range(0, len(audio), _CHUNK_MS)):

            chunk = audio[start_ms:start_ms + _CHUNK_MS]

            chunk_path = os.path.join(
                tempfile.gettempdir(),
                f"{os.path.basename(audio_path)}.part{i}.mp3"
            )

            chunk.export(chunk_path, format="mp3", bitrate="64k")
            chunk_paths.append(chunk_path)

        return chunk_paths

    # ==================================================
    # STEP 3 — SUMMARIZE TRANSCRIPT (LLM, map-reduce for long videos)
    # ==================================================

    def _summarize_transcript(
        self,
        transcript: str,
        topic: str,
        history_text: str,
        summary: str
    ) -> str:
        """
        Handles both short and very long transcripts (i.e. long
        videos), regardless of whether the transcript came from
        YouTube captions or Whisper — both paths converge here.
        """

        if len(transcript) <= _MAP_REDUCE_THRESHOLD_CHARS:
            return self._summarize_chunk(
                transcript=transcript,
                topic=topic,
                history_text=history_text,
                summary=summary,
                is_partial=False
            )

        # ---- Map step: summarize each piece independently ----
        pieces = [
            transcript[i:i + _MAP_CHUNK_CHARS]
            for i in range(0, len(transcript), _MAP_CHUNK_CHARS)
        ]

        partial_summaries = [
            self._summarize_chunk(
                transcript=piece,
                topic=topic,
                history_text="",
                summary="",
                is_partial=True
            )
            for piece in pieces
        ]

        combined = "\n\n".join(
            f"Part {i + 1}: {s}" for i, s in enumerate(partial_summaries)
        )

        # ---- Reduce step: combine partial summaries into one ----
        reduce_prompt = f"""
Your are Athena , an AI Tutor. Below are summaries of consecutive parts of a
single video's transcript, in order. Combine them into ONE coherent,
well-structured summary of the whole video — remove redundancy between
parts, preserve the overall narrative/argument, and organize it with
clear sections.

==================================================
PARTIAL SUMMARIES (IN ORDER)
==================================================
{combined}

==================================================
REQUEST CONTEXT
==================================================
{topic}

Produce the final combined summary now, using headings and bullet
points where helpful.
"""

        try:
            return route(
                prompt=reduce_prompt,
                provider=self.provider,
                model=self.model,
                purpose="answer"
            ).strip()

        except Exception as e:
            print(f"VideoSummaryAgent reduce-step error: {e}")
            # Fall back to just concatenating the partial summaries
            # rather than failing the whole request.
            return combined

    def _summarize_chunk(
        self,
        transcript: str,
        topic: str,
        history_text: str,
        summary: str,
        is_partial: bool
    ) -> str:

        scope_note = (
            "This is only ONE PART of a longer video's transcript — "
            "summarize just this part, in 3-6 bullet points. Don't "
            "add an intro/conclusion, since this will be merged with "
            "other parts later."
            if is_partial else
            """
Produce a clear, well-organized summary of the whole video with:
- A 2-3 sentence overview of what the video covers
- Key points as bullet points
- Any conclusions, takeaways, or action items mentioned
"""
        )

        prompt = f"""
Your are Athena , an AI Tutor. Summarize the following video transcript for a
student.

{scope_note}

Use conversation summary/history to resolve references like "it" or
"that video" if the user's request depends on them.

==================================================
CONVERSATION SUMMARY
==================================================
{summary}

==================================================
CONVERSATION HISTORY
==================================================
{history_text}

==================================================
USER REQUEST
==================================================
{topic}

==================================================
VIDEO TRANSCRIPT
==================================================
{transcript}

==================================================
SUMMARY
==================================================
"""

        try:
            return route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="answer"
            ).strip()

        except Exception as e:
            print(f"VideoSummaryAgent summarize error: {e}")
            return "Sorry, I could not summarize this part of the video."