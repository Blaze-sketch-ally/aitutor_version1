import re

from langsmith import traceable

from agents.chat_agent import ChatAgent
from agents.tutor_agent import TutorAgent
from agents.youtube_agent import YouTubeAgent
from agents.paper_agent import PaperAgent
from agents.quiz_agent import QuizAgent
from agents.notes_agent import NotesAgent
from agents.diagram_agent import DiagramAgent
from agents.video_summary_agent import VideoSummaryAgent, find_youtube_url
from agents.vision_agent import VisionAgent
from agents.intent_classifier import IntentClassifier
from agents.topic_extractor import TopicExtractor
from agents.query_resolver import QueryResolverAgent
from agents.comparison_agent import ComparisonAgent
from agents.cross_pdf_notes_agent import CrossPDFNotesAgent
from agents.cross_pdf_quiz_agent import CrossPDFQuizAgent
from agents.web_research_agent import WebResearchAgent
from agents.task_router_agent import TaskRouterAgent

from memory.chat_memory import ChatMemory
from memory.session_manager import SessionManager, SessionOwnershipError
from memory.conversation_summary import (
    RECENT_WINDOW,
    ConversationSummaryAgent,
    dump_stored_summary,
    load_stored_summary,
    plan_summary,
)

from models.errors import RetrievalError
from rag.retriever import Retriever, query_topic_terms


class Orchestrator:

    def __init__(
        self,
        user_id: str,
        session_id: str
    ):

        self.session_id = session_id
        self.user_id = user_id

        self.retriever = Retriever(
            session_id=session_id
        )

        self.memory = ChatMemory(
            user_id=user_id,
            session_id=session_id
        )
        self.session_manager = SessionManager(
            user_id=user_id
        )

        # Every chat/RAG/PDF-chat code path funnels through this
        # constructor — this is the narrowest chokepoint to reject a
        # session_id that doesn't exist or doesn't belong to user_id,
        # before any agent/retriever work happens for it. Routes also
        # check this earlier (api/pdf.py's upload), but requests can
        # reach the Orchestrator without going through those (e.g. any
        # future caller of load_orchestrator), so this stays a real
        # guard, not a redundant one.
        if not self.session_manager.session_exists(session_id):

            raise SessionOwnershipError(session_id)

        self.chat = ChatAgent()
        self.tutor = TutorAgent()

        self.youtube = YouTubeAgent()
        self.paper = PaperAgent()

        self.quiz = QuizAgent()
        self.notes = NotesAgent()
        self.diagram = DiagramAgent()
        self.video_summary = VideoSummaryAgent()
        self.vision = VisionAgent()

        self.intent_classifier = (
            IntentClassifier()
        )

        self.topic_extractor = (
            TopicExtractor()
        )

        self.summary_agent = (
            ConversationSummaryAgent()
        )

        self.query_resolver = (
            QueryResolverAgent()
        )
        self.comparison = ComparisonAgent()
        self.cross_notes = (
                        CrossPDFNotesAgent()
        )

        self.cross_quiz = (
                        CrossPDFQuizAgent()
        )

        self.web_research = (
            WebResearchAgent()
        )

        self.task_router = (
            TaskRouterAgent()
        )

    @traceable(
        name="Orchestrator.run_full_pipeline"
    )
    def run(
        self,
        query: str,
        marks: str = "8",
        selected_pdfs:list[str]|None=None,
        uploaded_video_path: str | None = None,
        image_attachments: list[dict] | None = None,
        prepared: dict | None = None
    ):
        """
        prepared: the dict from _prepare_turn() when the caller
        (run_stream) already prepared this turn; None -> prepared here.

        image_attachments (new): optional list of
        {"path": str, "mime_type": str, "filename": str} dicts, one per
        uploaded image for this turn (see api/chat.py's /images route
        and services/attachment_service.py). Each is read from its
        ephemeral temp file, passed to VisionAgent, and the resulting
        description is folded into `pdf_context` below — the same
        context slot every existing agent (Tutor/Quiz/Notes/Diagram/
        Comparison) already reads. This deliberately does NOT add a
        new intent or a new dispatch branch: intent classification and
        agent selection are completely unchanged, so "explain this"/
        "quiz me on this"/"make notes from this" continue to route
        through the existing agents exactly as they do for PDF context.
        """

        # =====================================
        # TURN PREPARATION (once per user message)
        # =====================================
        # Conversation context, query resolution and intent
        # classification are computed in _prepare_turn(). run_stream()
        # prepares the turn itself and hands it in here when it falls
        # back to this non-streamed path, so none of it runs twice.

        if prepared is None:

            prepared = self._prepare_turn(
                query=query,
                uploaded_video_path=uploaded_video_path,
                has_image=bool(image_attachments)
            )

        conversation_summary = prepared["summary"]
        resolver_result = prepared["resolver_result"]
        resolved_query = prepared["resolved_query"]
        history_text = prepared["history_text"]
        brief_history_text = prepared["brief_history_text"]

        # =====================================
        # VIDEO SUMMARY SHORT-CIRCUIT
        # =====================================
        # A pasted YouTube link or an uploaded video file is an
        # unambiguous signal: no intent classification, no PDF
        # retrieval (_prepare_turn skips both for these).

        youtube_url = prepared["youtube_url"]

        if youtube_url or uploaded_video_path:

            video_result = self.video_summary.summarize_video(
                youtube_url=youtube_url,
                uploaded_video_path=uploaded_video_path,
                topic=query,
                history_text=history_text,
                summary=conversation_summary
            )

            self.memory.add_message(
                message={
                    "role": "assistant",
                    "content": video_result.get("summary", ""),
                    "chat": video_result.get("summary", ""),
                    "videos": [],
                    "papers": [],
                    "diagram": None,
                    "sources": []
                }
            )

            return {
                "mode": "video_summary",
                "video_source": video_result.get("source"),
                "video_source_ref": video_result.get("source_ref"),
                "answer": video_result.get("summary", ""),
                "sources": []
            }

        intents = prepared["intents"]

        print("\n========== INTENTS ==========")
        print(intents)
        print("=============================\n")

        # =====================================
        # PDF RETRIEVAL + SOURCES
        # =====================================
        # See _retrieve_pdf_context() for when retrieval runs and how
        # explicit vs. implicit PDF questions are treated.

        retrieval = self._retrieve_pdf_context(
            query=query,
            resolved_query=resolved_query,
            intents=intents,
            selected_pdfs=selected_pdfs
        )

        knowledge_source = retrieval["knowledge_source"]
        pdf_context = retrieval["pdf_context"]
        pdf_contexts = retrieval["pdf_contexts"]
        sources = retrieval["sources"]
        strict_pdf = retrieval["strict_pdf"]
        pdf_searched = retrieval["pdf_searched"]
        whole_document = retrieval["whole_document"]

        has_pdf = bool(
            pdf_context.strip()
        ) or bool(
            pdf_contexts
    )

        # =====================================
        # IMAGE ATTACHMENTS (VisionAgent)
        # =====================================
        # Runs after PDF retrieval so a combined "image + PDF" turn
        # (e.g. "compare this diagram with my PDF") has both pieces of
        # context available together. Folds straight into pdf_context/
        # pdf_contexts rather than a separate response field, since
        # every downstream agent below already reads exactly those.

        if image_attachments:

            images_bytes = []
            image_mime_types = []

            for attachment in image_attachments:

                try:
                    with open(attachment["path"], "rb") as f:
                        images_bytes.append(f.read())
                    image_mime_types.append(
                        attachment.get("mime_type") or "image/png"
                    )
                except OSError as e:
                    print(
                        f"Orchestrator: could not read image "
                        f"attachment '{attachment.get('path')}': {e}"
                    )

            if images_bytes:

                vision_result = self.vision.analyze_images(
                    images=images_bytes,
                    image_mime_types=image_mime_types,
                    instruction=query,
                    context=pdf_context,
                    history_text=history_text,
                    summary=conversation_summary
                )

                vision_context = (
                    "The user attached the following image(s). Use "
                    "this understanding of them to answer the "
                    "request below:\n\n"
                    f"{vision_result.get('description', '')}"
                )

                if vision_result.get("detected_text"):
                    vision_context += (
                        "\n\nText detected in the image(s): "
                        f"{vision_result['detected_text']}"
                    )

                pdf_context = (
                    f"{pdf_context}\n\n{vision_context}".strip()
                    if pdf_context else vision_context
                )

                if pdf_contexts:
                    pdf_contexts["Attached Image(s)"] = vision_context

        # =====================================
        # DEBUG
        # =====================================

        print("\n========== DEBUG ==========")

        print(
            "Session:",
            self.session_id
        )

        print(
            "Query:",
            query
        )

        print(
            "Resolved Query:",
            resolved_query
        )

        print(
            "Follow Up:",
            resolver_result.get(
                "is_followup",
                False
            )
        )

        print(
            "Resolved Topic:",
            resolver_result.get(
                "resolved_topic",
                ""
            )
        )

        print(
            "Intents:",
            intents
        )

        print(
            "Knowledge Source:",
            knowledge_source
        )
        print(
                "Selected PDFs:",
                selected_pdfs
            )

        print(
            "PDF Context Found:",
            has_pdf
        )

        print(
            "Sources Found:",
            len(sources)
        )

        print(
            "Memory Size:",
            self.memory.size()
        )

        print(
            "Summary Generated:",
            bool(conversation_summary)
        )

        print("===========================\n")

        # =====================================
        # PURE CHAT MODE
        # =====================================

        is_only_chat = (

            intents.get("chat", False)

            and not intents.get(
                "answer",
                False
            )

            and not intents.get(
                "quiz",
                False
            )
            and not intents.get(
                "comparison",
                False
            )

            and not intents.get(
                "notes",
                False
            )

            and not intents.get(
                "diagram",
                False
            )

            and not intents.get(
                "videos",
                False
            )

            and not intents.get(
                "papers",
                False
            )

        )

        if is_only_chat:

            reply = self.chat.generate_reply(
                message=query,
                history_text=history_text,
                summary=conversation_summary
            )

            # In-memory only (persist=False by default) — app.py
            # persists the authoritative copy of this turn right
            # after run() returns. We used to ALSO call
            # session_manager.save_history() here, which wrote a
            # second, thinner copy of the whole conversation to the
            # same table straight after this one, immediately
            # clobbering it with a version missing every other
            # message's videos/papers/sources fields. Removed.
            self.memory.add_message(
                message={
                    "role": "assistant",
                    "content": reply,
                    "chat": reply,
                    "videos": [],
                    "papers": [],
                    "diagram": None,
                    "sources": []
                }
            )

            return {
                "mode": "chat",
                "chat": reply,
                "sources": []
            }
        # =====================================
        # RESPONSE OBJECT
        # =====================================

        response = {
            "mode": "mixed",
            "sources": sources
        }

        # =====================================
        # ANSWER
        # =====================================

        if intents.get(
            "answer",
            False
        ):

            response["answer"] = (
                self.tutor.generate_answer(
                    question=query,
                    context=pdf_context,
                    history_text=history_text,
                    summary=conversation_summary,
                    marks=marks,
                    strict_pdf=strict_pdf,
                    pdf_searched=pdf_searched
                )
            )

        # =====================================
        # NOTES
        # =====================================

        if intents.get(
            "notes",
            False
    ):

            if intents.get(
                "all_pdfs",
                False
            ):

                print("Cross PDF Notes PDFs:")
                print(pdf_contexts.keys())
                response["notes"] = (
                    self.cross_notes.generate_notes(
                        topic=query,
                        pdf_contexts=pdf_contexts
                    )
                )

            else:

                response["notes"] = (
                    self.notes.generate_notes(
                        topic=query,
                        context=pdf_context,
                        history_text=brief_history_text,
                        summary=conversation_summary,
                        strict_pdf=strict_pdf
                    )
                )
        # =====================================
# COMPARISON
# =====================================

        if intents.get(
            "comparison",
            False
        ):

            response["comparison"] = (
                self.comparison.generate_comparison(
                    topic=query,
                    pdf_contexts=pdf_contexts,
                    history_text=brief_history_text,
                    summary=conversation_summary,
                    strict_pdf=strict_pdf,
                    pdf_searched=pdf_searched,
                    # "compare the two PDFs" / "compare all PDFs" compares
                    # documents; "compare Tahoe and Reno" compares concepts.
                    compare_documents=bool(
                        intents.get("all_pdfs", False) or whole_document
                    )
                )
            )

        # =====================================
        # QUIZ
        # =====================================

        if intents.get(
    "quiz",
    False
):

            if intents.get(
                "all_pdfs",
                False
            ):

                print("Cross PDF Quiz PDFs:")
                print(pdf_contexts.keys())
                response["quiz"] = (
                    self.cross_quiz.generate_quiz(
                        topic=query,
                        pdf_contexts=pdf_contexts
                    )
                )

            else:

                response["quiz"] = (
                    self.quiz.generate_quiz(
                        topic=query,
                        context=pdf_context,
                        history_text=brief_history_text,
                        summary=conversation_summary,
                        strict_pdf=strict_pdf
                    )
                )

        # =====================================
        # DIAGRAM
        # =====================================

        if intents.get(
            "diagram",
            False
        ):

            diagram = self.diagram.generate_diagram(
                topic=query,
                context=pdf_context,
                history_text=brief_history_text,
                summary=conversation_summary,
                strict_pdf=strict_pdf
            )

            if isinstance(diagram, dict) and diagram.get("type") == "none":

                # e.g. a chart with no real numbers behind it — tell the
                # user instead of rendering a made-up visual.
                response["answer"] = (
                    response.get("answer", "")
                    + ("\n\n" if response.get("answer") else "")
                    + diagram.get("message", "")
                )

            else:

                response["diagram"] = diagram

        # =====================================
        # VIDEOS
        # =====================================
        # context here is pdf_context, which by this point already
        # includes the representative-content fallback (see the
        # retrieval block above) when knowledge_source is pdf/hybrid
        # and similarity search found nothing — no special-casing
        # needed here anymore.

        if intents.get(
            "videos",
            False
        ):

            response["videos"] = (
                self.youtube.get_videos(
                    query=query,
                    context=pdf_context,
                    history_text=brief_history_text,
                    summary=conversation_summary
                )
            )

        # =====================================
        # PAPERS
        # =====================================

        if intents.get(
            "papers",
            False
        ):

            response["papers"] = (
                self.paper.get_papers(
                    query=query,
                    context=pdf_context,
                    history_text=brief_history_text,
                    summary=conversation_summary
                )
            )

        # =====================================
        # WEB RESEARCH
        # =====================================

        if intents.get(
            "web_research",
            False
        ):

            web_result = (
                self.web_research.research(
                    query=query,
                    history_text=history_text,
                    summary=conversation_summary
                )
            )

            response["web_research"] = (
                web_result.get("answer", "")
            )

            response["web_sources"] = (
                web_result.get("results", [])
            )

        # =====================================
        # EXTERNAL ACTION
        # =====================================
        # Only set the response key when a verified action was actually
        # found — the "nothing found" case is handled entirely by the
        # empty-result notice block below, same as videos/papers/
        # web_research, rather than setting a null-action payload here.

        if intents.get(
            "external_action",
            False
        ):

            task_result = (
                self.task_router.route_task(
                    query=query,
                    history_text=history_text,
                    summary=conversation_summary
                )
            )

            if task_result.get("action"):

                response["external_action"] = task_result

        # =====================================
        # FALLBACK ANSWER
        # =====================================
        # NOTE: checks truthiness (`response.get(key)`), not just key
        # membership (`key in response`). The old `key in response`
        # check meant that if e.g. get_videos() hit an internal error
        # and returned [] (empty list, but the key still gets set),
        # this fallback thought "videos" was already handled and
        # skipped generating anything — producing a completely blank
        # response with no text and no error, which is exactly what
        # looked like nothing happening at all.

        if not any(
                response.get(key)
                for key in [
                    "answer",
                    "comparison",
                    "notes",
                    "quiz",
                    "diagram",
                    "videos",
                    "papers",
                    "web_research",
                    "external_action"
                ]
            ):

            response["answer"] = (
                self.tutor.generate_answer(
                    question=query,
                    context=pdf_context,
                    history_text=history_text,
                    summary=conversation_summary,
                    marks=marks,
                    strict_pdf=strict_pdf,
                    pdf_searched=pdf_searched
                )
            )

        # =====================================
        # NOTICE WHEN A REQUESTED FEATURE CAME BACK EMPTY
        # =====================================
        # If the user specifically asked for videos/papers and the
        # agent legitimately found nothing (or failed silently), say
        # so in plain text instead of leaving the bubble blank.

        if intents.get("videos", False) and not response.get("videos"):

            response["answer"] = (
                response.get("answer", "")
                + ("\n\n" if response.get("answer") else "")
                + "I couldn't find any matching YouTube videos for "
                  "this right now — this can happen if the topic is "
                  "very narrow, or if the video search is temporarily "
                  "unavailable."
            )

        if intents.get("papers", False) and not response.get("papers"):

            response["answer"] = (
                response.get("answer", "")
                + ("\n\n" if response.get("answer") else "")
                + "I couldn't find any matching research papers for "
                  "this right now."
            )

        if intents.get("web_research", False) and not response.get("web_research"):

            response["answer"] = (
                response.get("answer", "")
                + ("\n\n" if response.get("answer") else "")
                + "I couldn't find current information on this right "
                  "now — this can happen if the topic is very narrow, "
                  "or if live web search is temporarily unavailable."
            )

        if intents.get("external_action", False) and not response.get("external_action"):

            response["answer"] = (
                response.get("answer", "")
                + ("\n\n" if response.get("answer") else "")
                + "I couldn't find a verified official source for this "
                  "— you may want to search for it yourself to be safe."
            )

        # =====================================
        # TRACK ASSISTANT RESPONSE (in-memory only)
        # =====================================
        # Same reasoning as the user-message tracking above: this
        # updates ChatMemory's in-process buffer (so a later turn in
        # the same run/session has correct history_text) but does NOT
        # persist. app.py builds and saves the full rich message dict
        # (including videos/papers/sources, which this flattened
        # memory_text string deliberately omits) right after run()
        # returns — that save is authoritative.

        memory_text = ""

        if "answer" in response:
            memory_text += response["answer"]

        if "comparison" in response:
            memory_text += "\n\n" + response["comparison"]

        if "notes" in response:
            memory_text += "\n\n" + response["notes"]

        if "quiz" in response:
            memory_text += "\n\n" + response["quiz"]

        if "web_research" in response:
            memory_text += "\n\n" + response["web_research"]

        if "external_action" in response:
            memory_text += "\n\n" + (response["external_action"].get("message") or "")

        if "diagram" in response:
            # response["diagram"] is a dict (see DiagramAgent.generate_diagram),
            # e.g. {"type": "mermaid"/"chart"/"image", "content": ..., "prompt": ...}.
            # Memory only needs a short readable summary for follow-up context,
            # not the raw mermaid code / chart JSON / image url — so convert
            # it to text instead of trying to concatenate the dict directly
            # (that direct concatenation was the cause of a TypeError).
            memory_text += "\n\n" + self._diagram_to_text(
                response["diagram"]
            )

        if memory_text.strip():

            self.memory.add_message(
                "assistant",
                memory_text
            )
    

        return response

    # =====================================================
    # TURN PREPARATION
    # =====================================================
    # Everything that must happen exactly once per user message, before
    # any agent runs:
    #   1. conversation context — rolling summary (refreshed only every
    #      few turns, FAST_MODEL) + a clipped recent-history window
    #   2. query resolution — only when the query refers back to earlier
    #      turns (FAST_MODEL); self-contained questions skip it
    #   3. tracking the user message / first-message title
    #   4. intent classification — deterministic rules first, LLM only
    #      for ambiguous requests; skipped entirely for video turns
    # run() and run_stream() both consume this dict; neither recomputes
    # any of it.

    # Per-message character caps for the history each consumer gets.
    AGENT_HISTORY_CHARS = 800          # older messages in the window
    AGENT_HISTORY_LATEST_CHARS = 2000  # last answer + current question
    BRIEF_HISTORY_MESSAGES = 4         # notes/quiz/diagram/comparison
    BRIEF_HISTORY_CHARS = 400
    RESOLVER_HISTORY_MESSAGES = 4
    RESOLVER_HISTORY_CHARS = 500
    RESOLVER_HISTORY_LATEST_CHARS = 1500

    def _conversation_context(self, messages: list) -> dict:
        """
        Rolling summary + where the verbatim window starts. See
        memory/conversation_summary.py for the policy. Summary text is
        conversation memory only — never document evidence.
        """

        if len(messages) <= RECENT_WINDOW:
            return {"summary": "", "recent_start": 0}

        session = self.session_manager.load_session(self.session_id) or {}
        stored = load_stored_summary(session.get("summary"))

        plan = plan_summary(len(messages), stored["covered"])
        summary = stored["text"] if plan["recent_start"] == stored["covered"] else ""

        if plan["refresh"]:

            start = stored["covered"] if stored["covered"] <= len(messages) else 0
            previous = stored["text"] if start else ""

            summary = self.summary_agent.update_summary(
                previous_summary=previous,
                new_messages_text=ChatMemory.format_messages(
                    messages[start:plan["covered"]],
                    max_chars=self.BRIEF_HISTORY_CHARS
                )
            )

            try:
                self.session_manager.update_summary(
                    self.session_id,
                    dump_stored_summary(plan["covered"], summary)
                )
            except Exception as e:
                # Not fatal: next turn simply refreshes again.
                print(f"Could not store conversation summary: {e}")

        return {"summary": summary, "recent_start": plan["recent_start"]}

    def _prepare_turn(
        self,
        query: str,
        uploaded_video_path: str | None = None,
        has_image: bool = False
    ) -> dict:

        previous_messages = list(self.memory.get_full_history() or [])

        context = self._conversation_context(previous_messages)

        youtube_url = find_youtube_url(query)
        is_video = bool(youtube_url or uploaded_video_path)

        if not is_video and self.query_resolver.needs_resolution(
            query, has_history=bool(previous_messages)
        ):

            resolver_result = self.query_resolver.resolve(
                query=query,
                history_text=ChatMemory.format_messages(
                    previous_messages[-self.RESOLVER_HISTORY_MESSAGES:],
                    max_chars=self.RESOLVER_HISTORY_CHARS,
                    latest_max_chars=self.RESOLVER_HISTORY_LATEST_CHARS
                ),
                summary=context["summary"]
            )

        else:

            resolver_result = {
                "is_followup": False,
                "resolved_topic": query,
                "resolved_query": query
            }

        resolved_query = resolver_result.get("resolved_query") or query

        # In-memory only; ChatAPIService persists the durable copy after
        # the turn completes.
        self.memory.add_message("user", query)

        if self.memory.size() == 1:

            self.session_manager.update_title(
                self.session_id,
                query[:50]
            )

        history_text = self.memory.get_history_text(
            start=context["recent_start"],
            max_chars=self.AGENT_HISTORY_CHARS,
            latest_max_chars=self.AGENT_HISTORY_LATEST_CHARS
        )

        brief_history_text = self.memory.get_history_text(
            max_turns=self.BRIEF_HISTORY_MESSAGES,
            max_chars=self.BRIEF_HISTORY_CHARS
        )

        intents = (
            None if is_video
            # has_image: a question about an attached image is image
            # understanding, not a request to generate a picture.
            else self.intent_classifier.classify(
                resolved_query, has_image=has_image
            )
        )

        return {
            "summary": context["summary"],
            "resolver_result": resolver_result,
            "resolved_query": resolved_query,
            "history_text": history_text,
            "brief_history_text": brief_history_text,
            "youtube_url": youtube_url,
            "intents": intents,
        }

    # =====================================================
    # PDF RETRIEVAL PLANNING
    # =====================================================
    # Decides whether to search the session's PDFs for this turn and
    # how strictly to use what comes back. Three cases:
    #
    #   explicit — the query names the material ("according to the
    #     PDF", "from the document", "in the uploaded file"), or the
    #     classifier chose pdf/hybrid. Checked on the ORIGINAL query
    #     too, because QueryResolver's rewrite can drop the phrase.
    #     knowledge_source "pdf" => strict: answer only from the PDF,
    #     and say so when it isn't there.
    #
    #   implicit — nothing names the material, but the user has PDFs
    #     selected and asked for tutoring content (answer/notes/quiz/
    #     comparison/diagram). This is the "how does X work?" / "why
    #     ...?" case the classifier's follow-up shortcut used to force
    #     to general. Retrieval is attempted; its relevance filter
    #     decides whether anything in the PDF actually bears on the
    #     question, so an unrelated question just gets no context (and
    #     a note that the selected PDF doesn't cover it) instead of
    #     being forced through the PDF.
    #
    #   none — no PDFs involved (or pure chat / web / external action).
    #
    # The representative-sample fallback (a slice of the PDF with no
    # similarity search) is only for whole-document requests such as
    # "summarize the pdf" / "make notes from my document", whose wording
    # has nothing to match semantically. It is never used to pad a
    # specific question that the PDF simply doesn't answer.

    _CONTENT_INTENTS = ("answer", "notes", "quiz", "comparison", "diagram")

    def _retrieve_pdf_context(
        self,
        query: str,
        resolved_query: str,
        intents: dict,
        selected_pdfs: list[str] | None
    ) -> dict:

        knowledge_source = intents.get("knowledge_source", "general")

        explicit = (
            knowledge_source in ("pdf", "hybrid")
            or IntentClassifier.references_pdf(query)
        )

        if explicit and knowledge_source == "general":
            knowledge_source = "pdf"

        implicit = (
            not explicit
            and bool(selected_pdfs)
            and any(intents.get(k, False) for k in self._CONTENT_INTENTS)
        )

        grouped = bool(
            intents.get("all_pdfs", False)
            or intents.get("comparison", False)
        )

        whole_document = explicit and not query_topic_terms(query)

        result = {
            "knowledge_source": knowledge_source,
            "pdf_context": "",
            "pdf_contexts": {},
            "sources": [],
            "strict_pdf": knowledge_source == "pdf",
            "pdf_searched": False,
            "whole_document": whole_document
        }

        # A comparison is searched like any other content request:
        # explicitly referenced, or PDFs selected (implicit). With no
        # PDF involved it's a general-knowledge comparison.
        should_search = explicit or implicit

        print(
            f"PDF retrieval plan: explicit={explicit} implicit={implicit} "
            f"whole_document={whole_document} grouped={grouped} "
            f"knowledge_source={knowledge_source}"
        )

        if not should_search:
            return result

        try:

            if not self.retriever.has_documents():
                return result

            result["pdf_searched"] = True

            if grouped:

                grouped_result = self.retriever.get_grouped_context_by_source(
                    resolved_query,
                    selected_pdfs=selected_pdfs,
                    top_k=5
                )

                result["pdf_contexts"] = grouped_result.get("pdf_contexts", {})
                result["sources"] = grouped_result.get("sources", [])

            else:

                retrieval_result = self.retriever.get_context_with_sources(
                    query=resolved_query,
                    selected_pdfs=selected_pdfs,
                    top_k=5
                )

                result["pdf_context"] = retrieval_result.get("context", "")
                result["sources"] = retrieval_result.get("sources", [])

            no_context_found = (
                not result["pdf_context"].strip()
                and not result["pdf_contexts"]
            )

            if no_context_found and selected_pdfs and whole_document:

                representative = self.retriever.get_representative_context(
                    selected_pdfs=selected_pdfs
                )

                if representative:

                    print(
                        "Whole-document request with no similarity "
                        "matches; using representative PDF content."
                    )

                    if grouped:
                        result["pdf_contexts"] = representative
                    else:
                        result["pdf_context"] = "\n\n".join(
                            representative.values()
                        )

        except RetrievalError as e:

            # The search itself failed. Don't answer as if the PDF had
            # nothing relevant (or, worse, from general knowledge for an
            # explicit PDF question) — the API turns this into a
            # temporary-error response.
            print(f"Retrieval failed for this turn: {e}")
            raise

        except Exception as e:

            print(f"Retriever Error: {e}")

            result["pdf_context"] = ""
            result["pdf_contexts"] = {}
            result["sources"] = []

        return result

    @staticmethod
    def _diagram_to_text(diagram: dict) -> str:
        """
        Converts the DiagramAgent's structured dict output into a short
        plain-text summary for storing in chat memory (history_text).
        Memory just needs something readable for follow-up context —
        it doesn't need the full mermaid code / chart JSON / image url.
        """

        if not isinstance(diagram, dict):
            return str(diagram)

        d_type = diagram.get("type")

        if d_type == "mermaid":
            return "[Generated a mermaid diagram for this request.]"

        if d_type == "chart":
            content = diagram.get("content", {})
            title = (
                content.get("title", "a chart")
                if isinstance(content, dict) else "a chart"
            )
            return f"[Generated a chart: {title}]"

        if d_type == "image":
            prompt = diagram.get("prompt", "")
            return (
                f"[Generated an image for: {prompt}]"
                if prompt else "[Generated an image.]"
            )

        return "[Generated a diagram/visual.]"

    # =====================================================
    # STREAMING ENTRY POINT
    # =====================================================
    # Only the two simplest, most common cases stream:
    #   1. Pure chat (is_only_chat)
    #   2. "answer" is the ONLY requested intent (no notes/quiz/
    #      diagram/videos/papers/comparison alongside it)
    #
    # Those are the cases where there's nothing else for the response
    # dict to wait on, so streaming the text actually reduces
    # perceived latency. Everything else (video-summary short-circuit,
    # any multi-intent combination) delegates straight to the
    # existing run() — unchanged, non-streaming — since those return
    # structured data (lists/dicts) that can't be "streamed" the same
    # way and already need to be fully computed before rendering.
    #
    # Returns a dict with:
    #   {"streamed": True,  "mode": "chat"/"answer", "generator": <gen>,
    #    "sources": [...]}   <- caller must consume the generator (e.g.
    #                            via st.write_stream), then call
    #                            finalize_stream(result, full_text)
    # or:
    #   {"streamed": False, ...same shape as run()...}

    def run_stream(
        self,
        query: str,
        marks: str = "8",
        selected_pdfs: list[str] | None = None,
        uploaded_video_path: str | None = None
    ):

        # Summary / resolution / classification happen ONCE here and are
        # handed to run() for every non-streamed case below — the old
        # code redid all three inside run() (up to 3 extra LLM calls).
        prepared = self._prepare_turn(
            query=query,
            uploaded_video_path=uploaded_video_path
        )

        if prepared["youtube_url"] or uploaded_video_path:

            result = self.run(
                query=query,
                marks=marks,
                selected_pdfs=selected_pdfs,
                uploaded_video_path=uploaded_video_path,
                prepared=prepared
            )
            result["streamed"] = False

            return result

        conversation_summary = prepared["summary"]
        resolved_query = prepared["resolved_query"]
        history_text = prepared["history_text"]
        intents = prepared["intents"]

        is_only_chat = (

            intents.get("chat", False)
            and not any(
                intents.get(key, False)
                for key in (
                    "answer", "quiz", "comparison", "notes",
                    "diagram", "videos", "papers"
                )
            )
        )

        is_answer_only = (

            intents.get("answer", False)
            and not any(
                intents.get(key, False)
                for key in (
                    "quiz", "comparison", "notes",
                    "diagram", "videos", "papers"
                )
            )
        )

        # Same retrieval rules as run() (see _retrieve_pdf_context);
        # only needed for the streamed answer path — pure chat uses no
        # PDF context, and every other case re-enters run() below.
        retrieval = {
            "pdf_context": "",
            "sources": [],
            "strict_pdf": False,
            "pdf_searched": False
        }

        if is_answer_only and not is_only_chat:

            retrieval = self._retrieve_pdf_context(
                query=query,
                resolved_query=resolved_query,
                intents=intents,
                selected_pdfs=selected_pdfs
            )

        pdf_context = retrieval["pdf_context"]
        sources = retrieval["sources"]
        strict_pdf = retrieval["strict_pdf"]
        pdf_searched = retrieval["pdf_searched"]

        if is_only_chat:

            generator = self.chat.generate_reply_stream(
                message=query,
                history_text=history_text,
                summary=conversation_summary
            )

            return {
                "streamed": True,
                "mode": "chat",
                "generator": generator,
                "sources": []
            }

        if is_answer_only:

            generator = self.tutor.generate_answer_stream(
                question=query,
                context=pdf_context,
                history_text=history_text,
                summary=conversation_summary,
                marks=marks,
                strict_pdf=strict_pdf,
                pdf_searched=pdf_searched
            )

            return {
                "streamed": True,
                "mode": "answer",
                "generator": generator,
                "sources": sources
            }

        # Anything else (multiple intents, notes/quiz/diagram/...) is
        # not streamed: fall back to run() with the SAME prepared turn,
        # so nothing above is recomputed.

        result = self.run(
            query=query,
            marks=marks,
            selected_pdfs=selected_pdfs,
            uploaded_video_path=uploaded_video_path,
            prepared=prepared
        )
        result["streamed"] = False

        return result

    def finalize_stream(self, result: dict, full_text: str):
        """
        Call this AFTER fully consuming result["generator"] (e.g. after
        st.write_stream() returns), passing the complete text it
        produced. Persists the turn into ChatMemory's in-process buffer
        — the same bookkeeping run() does internally for the
        is_only_chat / answer-only branches, just deferred until the
        streamed text actually exists.

        app.py still owns saving the authoritative copy to Supabase
        (same as every other path) — this only updates in-memory
        history_text for the rest of this session's turns.
        """

        mode = result.get("mode")

        if mode == "chat":

            self.memory.add_message(
                message={
                    "role": "assistant",
                    "content": full_text,
                    "chat": full_text,
                    "videos": [],
                    "papers": [],
                    "diagram": None,
                    "sources": []
                }
            )

            result["chat"] = full_text

        elif mode == "answer":

            self.memory.add_message(
                "assistant",
                full_text
            )

            result["answer"] = full_text

        result.pop("generator", None)

        return result