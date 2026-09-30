import json
import os
import time

from models.errors import ServiceUnavailableError
from models.metrics import RequestMetrics, record_timing
from services.orchestrator_service import load_orchestrator
from services.chat_services import ChatService
from services.session_service import SessionService


GENERIC_ERROR = "Something went wrong while generating a response. Please try again."


def _sse(event_type: str, payload: dict) -> str:
    """
    Formats one Server-Sent-Events frame: "data: <json>\\n\\n". Payload
    always includes "type" so the frontend can dispatch on it without a
    second field.
    """

    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _build_assistant_text(result: dict) -> str:
    """
    Mirrors app_new.py's build_assistant_text() for chat/answer/
    comparison/notes/quiz, plus web_research (not present in
    app_new.py) — concatenates whichever fields are present into one
    displayable string.
    """

    text = ""

    if result.get("chat"):
        text += result["chat"] + "\n\n"

    if result.get("answer"):
        text += result["answer"] + "\n\n"

    if result.get("comparison"):
        text += "Comparison\n\n" + result["comparison"] + "\n\n"

    if result.get("notes"):
        text += "Notes\n\n" + result["notes"] + "\n\n"

    if result.get("quiz"):
        text += "Quiz\n\n" + result["quiz"] + "\n\n"

    if result.get("web_research"):
        text += result["web_research"] + "\n\n"

    if result.get("external_action", {}).get("message"):
        text += result["external_action"]["message"] + "\n\n"

    return text.strip()


class ChatAPIService:

    def __init__(self):
        self.session_service = SessionService()

    def run(
        self,
        user_id: str,
        session_id: str,
        query: str,
        selected_pdfs: list,
        uploaded_video_path: str = None,
        image_attachments: list = None
    ):

        metrics = RequestMetrics("chat")

        try:
            with metrics.active():
                return self._run(
                    user_id, session_id, query, selected_pdfs,
                    uploaded_video_path, image_attachments
                )
        finally:
            metrics.finish()

    def _run(
        self,
        user_id: str,
        session_id: str,
        query: str,
        selected_pdfs: list,
        uploaded_video_path: str = None,
        image_attachments: list = None
    ):

        setup_started = time.perf_counter()

        orchestrator = load_orchestrator(
            user_id,
            session_id
        )

        record_timing("setup", (time.perf_counter() - setup_started) * 1000)

        chat_service = ChatService(
            orchestrator
        )

        result = chat_service.run_chat(
            query=query,
            selected_pdfs=selected_pdfs,
            uploaded_video_path=uploaded_video_path,
            image_attachments=image_attachments
        )

        self._persist_turn(
            user_id=user_id,
            session_id=session_id,
            query=query,
            selected_pdfs=selected_pdfs,
            uploaded_video_path=uploaded_video_path,
            result=result,
            image_attachments=image_attachments
        )

        return result

    def stream(
        self,
        user_id: str,
        session_id: str,
        query: str,
        selected_pdfs: list
    ):
        """
        Metrics wrapper around _stream(). StreamingResponse resumes this
        generator on different worker threads, so the request's metrics
        are re-activated around every resume instead of set once.
        """

        metrics = RequestMetrics("chat_stream")
        frames = self._stream(user_id, session_id, query, selected_pdfs)

        try:
            while True:
                with metrics.active():
                    try:
                        frame = next(frames)
                    except StopIteration:
                        break
                yield frame
        finally:
            metrics.finish()

    def _stream(
        self,
        user_id: str,
        session_id: str,
        query: str,
        selected_pdfs: list
    ):
        """
        Generator counterpart to run() for plain-text turns (no image/
        video attachments — those keep using the existing non-streaming
        run() above unchanged). Reuses Orchestrator.run_stream(), which
        already only streams the two simple cases (pure chat / answer-
        only) and transparently falls back to the full non-streaming
        run() for everything else (quiz/notes/diagram/videos/papers/
        comparison/video-summary) — this method doesn't need to know
        which case it got; it just forwards whatever run_stream()
        decided.

        Yields SSE frames:
          - {"type": "start", "mode", "sources"}   (streamed case only)
          - {"type": "chunk", "content"}            (streamed case only)
          - {"type": "done", "result": {...}}        (always, last frame)
          - {"type": "error", "message"}             (on failure)

        Persistence reuses _persist_turn() exactly as run() does, so a
        streamed turn ends up saved identically to a non-streamed one.
        """

        try:
            setup_started = time.perf_counter()
            orchestrator = load_orchestrator(user_id, session_id)
            record_timing("setup", (time.perf_counter() - setup_started) * 1000)

            result = orchestrator.run_stream(
                query=query,
                selected_pdfs=selected_pdfs
            )
        except ServiceUnavailableError as e:
            yield _sse("error", {"message": e.user_message})
            return
        except Exception as e:
            print(f"Chat stream failed: {type(e).__name__}: {e}")
            yield _sse("error", {"message": GENERIC_ERROR})
            return

        if not result.get("streamed"):

            try:
                self._persist_turn(
                    user_id=user_id,
                    session_id=session_id,
                    query=query,
                    selected_pdfs=selected_pdfs,
                    uploaded_video_path=None,
                    result=result,
                    image_attachments=None
                )
            except Exception as e:
                print(f"History persistence error (stream, non-streamed branch): {e}")

            yield _sse("done", {"result": result})
            return

        yield _sse(
            "start",
            {
                "mode": result.get("mode"),
                "sources": result.get("sources", [])
            }
        )

        generator = result["generator"]
        full_text = ""

        try:
            for chunk in generator:
                full_text += chunk
                yield _sse("chunk", {"content": chunk})
        except Exception as e:
            if isinstance(e, ServiceUnavailableError):
                message = e.user_message
            else:
                print(f"Chat stream failed mid-answer: {type(e).__name__}: {e}")
                message = GENERIC_ERROR
            yield _sse("error", {"message": message})
            if not full_text:
                # Nothing was generated — don't persist a fake
                # assistant reply for a turn that failed outright.
                return

        final_result = orchestrator.finalize_stream(result, full_text)

        try:
            self._persist_turn(
                user_id=user_id,
                session_id=session_id,
                query=query,
                selected_pdfs=selected_pdfs,
                uploaded_video_path=None,
                result=final_result,
                image_attachments=None
            )
        except Exception as e:
            print(f"History persistence error (stream, streamed branch): {e}")

        yield _sse("done", {"result": final_result})

    def persist_partial(
        self,
        user_id: str,
        session_id: str,
        query: str,
        selected_pdfs: list,
        mode: str,
        partial_text: str,
        sources: list = None
    ):
        """
        Persists a turn that was cut short by the user clicking Stop
        mid-stream. The frontend has already accumulated whatever text
        arrived before it aborted the fetch — this just saves that text
        through the exact same _persist_turn() path a completed turn
        uses, tagged with stopped=True, so reloading the session shows
        the partial answer instead of losing it or leaving a gap.
        """

        result = {
            "mode": mode,
            "sources": sources or [],
            "stopped": True
        }

        if mode == "chat":
            result["chat"] = partial_text
        else:
            result["answer"] = partial_text

        self._persist_turn(
            user_id=user_id,
            session_id=session_id,
            query=query,
            selected_pdfs=selected_pdfs,
            uploaded_video_path=None,
            result=result,
            image_attachments=None
        )

        return result

    def _persist_turn(
        self,
        user_id: str,
        session_id: str,
        query: str,
        selected_pdfs: list,
        uploaded_video_path: str,
        result: dict,
        image_attachments: list = None
    ):
        """
        Loads existing history, appends this turn's user + assistant
        messages (same rich shape app_new.py saved: content plus every
        extras field), and saves the full list back. Wrapped in
        try/except so a persistence failure never breaks the chat
        response itself — same "fail soft" approach as the rest of
        this codebase (e.g. Orchestrator's retriever try/except).
        """

        try:
            history = self.session_service.get_history(
                user_id=user_id,
                session_id=session_id
            ) or []

            attachment_prefixes = []

            if uploaded_video_path:
                attachment_prefixes.append(
                    f"📎 {os.path.basename(uploaded_video_path)}"
                )

            if image_attachments:
                for attachment in image_attachments:
                    filename = attachment.get("filename") or os.path.basename(
                        attachment.get("path", "image")
                    )
                    attachment_prefixes.append(f"🖼️ {filename}")

            display_text = query
            if attachment_prefixes:
                prefix = "\n".join(attachment_prefixes)
                display_text = f"{prefix}\n\n{query}" if query else prefix

            user_message = {
                "role": "user",
                "content": display_text
            }

            assistant_text = _build_assistant_text(result)

            if result.get("sources"):
                assistant_text += "\n\n📚 PDFs Used:\n"
                unique_pdfs = sorted({
                    source.get("source", "Unknown PDF")
                    for source in result["sources"]
                    if isinstance(source, dict)
                })
                for pdf in unique_pdfs:
                    assistant_text += f"\n• {pdf}"

            assistant_message = {
                "role": "assistant",
                "content": assistant_text,
                "chat": result.get("chat"),
                "answer": result.get("answer"),
                "comparison": result.get("comparison"),
                "notes": result.get("notes"),
                "quiz": result.get("quiz"),
                "diagram": result.get("diagram"),
                "videos": result.get("videos", []),
                "papers": result.get("papers", []),
                "web_research": result.get("web_research"),
                "web_sources": result.get("web_sources", []),
                "external_action": result.get("external_action"),
                "sources": result.get("sources", []),
                "mode": result.get("mode"),
                "video_source": result.get("video_source"),
                "video_source_ref": result.get("video_source_ref"),
                "selected_pdfs": selected_pdfs,
                "stopped": result.get("stopped", False)
            }

            history.append(user_message)
            history.append(assistant_message)

            self.session_service.save_history(
                user_id=user_id,
                session_id=session_id,
                messages=history
            )

        except Exception as e:
            print(f"History persistence error: {e}")