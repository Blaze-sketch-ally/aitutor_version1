import json
import re

from langsmith import traceable
from models.errors import LLMQuotaExhaustedError
from models.router import route


class IntentClassifier:

    def __init__(
        self,
        provider="groq",
        model=None
    ):
        self.provider = provider
        self.model = model

    def _apply_video_override(self, result: dict, q: str) -> dict:
        """
        Safety net: if the query clearly asks for video(s)/YouTube and
        the classifier (LLM or an earlier shortcut branch) didn't set
        videos=True, force it. Without this, a query like "give me
        youtube videos on X" can get misclassified as a plain
        answer/chat request — which routes to the LLM chat agent
        instead of the real YouTubeAgent, and the LLM will then
        HALLUCINATE a plausible-looking list of channels and fake
        /channel/UC... URLs from its own training data instead of
        real search results. This has been observed in practice, not
        theoretical — hence the hard override rather than relying on
        the LLM to classify it correctly every time.
        """

        if re.search(r"\bvideos?\b", q) or "youtube" in q:

            result["videos"] = True

        return result

    # ----------------------------------------------------------------
    # DIAGRAM OVERRIDE
    # ----------------------------------------------------------------
    # Same rationale as _apply_video_override above: none of the
    # worked examples in the LLM prompt used to show diagram=true, so
    # the classifier reliably missed requests like "give images of
    # messi" or "generate a parabolic graph" and routed them to plain
    # chat/answer instead of DiagramAgent. Hard keyword override, same
    # pattern as the video safety net, so this doesn't depend on the
    # LLM getting it right every time.

    _DIAGRAM_WORD_HINTS = (
        "diagram", "flowchart", "mermaid", "illustration",
        "artwork", "parabola", "parabolic"
    )

    _DIAGRAM_PHRASE_HINTS = (
        "flow chart", "mind map", "mindmap", "block diagram",
        "picture of", "pictures of", "image of", "images of",
        "photo of", "photos of", "photograph of", "poster of",
        "draw a", "drawing of", "generate image", "generate a picture",
        "generate a graph", "generate graph", "generate a chart",
        "generate chart", "plot the", "plot of", "graph of",
        "visualize the", "visualise the", "bar chart", "pie chart",
        "line chart", "bar graph", "line graph", "scatter plot",
        "histogram", "sequence diagram", "architecture diagram",
        "create a chart", "make a chart", "draw an"
    )

    def _apply_diagram_override(self, result: dict, q: str) -> dict:

        if (
            any(
                re.search(r"\b" + re.escape(word) + r"\b", q)
                for word in self._DIAGRAM_WORD_HINTS
            )
            or any(phrase in q for phrase in self._DIAGRAM_PHRASE_HINTS)
        ):

            result["diagram"] = True

        return result

    # ----------------------------------------------------------------
    # DIAGRAM -> ANSWER SUPPRESSION OVERRIDE
    # ----------------------------------------------------------------
    # A pure visual request like "generate image of football" or
    # "give graph of parabola" should NOT also trigger
    # TutorAgent.generate_answer(). None of the worked examples in the
    # LLM prompt show diagram=true paired with answer=false strongly
    # enough, so the classifier frequently sets answer=true alongside
    # diagram=true for these requests too. Orchestrator then makes a
    # second, completely separate route() call for the answer — if
    # THAT call fails/times out for any reason, TutorAgent silently
    # swallows the exception and returns its hardcoded
    # "Sorry, I could not generate an answer." string, which shows up
    # in the UI right next to a perfectly successful diagram/image,
    # looking exactly like the diagram generation itself failed even
    # though it didn't.
    #
    # If diagram is set and the query has no language indicating the
    # user ALSO wants a written explanation, drop answer to False so
    # TutorAgent is never called for a pure "show me a picture/graph"
    # request. Explicit combined requests like "explain X and give a
    # diagram" still keep answer=True since "explain" is in the hints.

    _EXPLANATION_HINTS = (
        "explain", "what is", "what are", "describe", "definition",
        "meaning of", "tell me about", "elaborate", "why", "how does",
        "how do", "notes on", "difference between", "summarize",
        "summarise"
    )

    def _apply_diagram_answer_override(self, result: dict, q: str) -> dict:

        if result.get("diagram") and not any(
            hint in q for hint in self._EXPLANATION_HINTS
        ):

            result["answer"] = False

        return result

    # ----------------------------------------------------------------
    # KNOWLEDGE SOURCE OVERRIDE
    # ----------------------------------------------------------------
    # Same rationale again: "give me notes from the pdf" / "answer
    # this from my pdf" can get classified with knowledge_source=
    # "general" by the LLM step, same reliability gap as the video/
    # diagram misses above. When that happens, Orchestrator.run()'s
    # entire PDF-retrieval block never runs (it's gated on
    # knowledge_source in ["pdf","hybrid"]) — so pdf_context stays
    # empty and every downstream agent quietly generates from general
    # knowledge instead of the uploaded document. This looks exactly
    # like "notes from PDF isn't working" even though nothing errors.

    _PDF_REFERENCE_HINTS = (
        "pdf", "pdfs", "document", "documents", "uploaded", "attachment"
    )

    # "the file" / "this material" / "my notes" etc. Bare "file" or
    # "notes" are too generic ("how do I open a file", "make notes on
    # X") to count on their own, so these need a determiner.
    _PDF_REFERENCE_PHRASE_RE = re.compile(
        r"\b(the|this|my|uploaded|attached|selected|given|provided)\s+"
        r"(file|files|doc|docs|material|materials|notes|reading|"
        r"handout|chapter|slides)\b"
    )

    @classmethod
    def references_pdf(cls, text: str) -> bool:
        """True when the text explicitly points at the uploaded
        material ("according to the PDF", "from the document", "in the
        uploaded file"). Also used by Orchestrator on the ORIGINAL
        query, since QueryResolver's rewrite can drop the phrase."""

        q = (text or "").lower()

        return bool(
            any(
                re.search(r"\b" + re.escape(hint) + r"\b", q)
                for hint in cls._PDF_REFERENCE_HINTS
            )
            or cls._PDF_REFERENCE_PHRASE_RE.search(q)
        )

    def _apply_knowledge_source_override(self, result: dict, q: str) -> dict:

        if result.get("knowledge_source") == "general" and self.references_pdf(q):

            result["knowledge_source"] = "pdf"
            result["resource_source"] = "pdf"

        return result

    # ----------------------------------------------------------------
    # WEB RESEARCH OVERRIDE
    # ----------------------------------------------------------------
    # Same rationale as the video/diagram overrides above: current-
    # events/current-info requests need a hard keyword safety net
    # rather than relying on the LLM step to catch them every time,
    # since a miss here means the LLM answers from stale training data
    # (or worse, hallucinates something that sounds current) instead of
    # actually being routed to WebResearchAgent's live search.

    _WEB_RESEARCH_HINTS = (
        "latest news", "current news", "recent news", "breaking news",
        "today's news", "todays news", "current events", "recent events",
        "recent developments", "latest developments", "what's happening",
        "whats happening", "up to date", "up-to-date", "as of today",
        "as of now", "this week's", "this weeks"
    )

    def _apply_web_research_override(self, result: dict, q: str) -> dict:

        if any(hint in q for hint in self._WEB_RESEARCH_HINTS):

            result["web_research"] = True

        return result

    # ----------------------------------------------------------------
    # WEB RESEARCH -> ANSWER SUPPRESSION OVERRIDE
    # ----------------------------------------------------------------
    # Same pattern as _apply_diagram_answer_override: a pure "what's
    # the latest news on X" request should not ALSO trigger
    # TutorAgent.generate_answer() — that would sit a stale/frozen-
    # training-data answer right next to the fresh, web-grounded one,
    # which is confusing at best and contradictory at worst. Reuses
    # the same _EXPLANATION_HINTS tuple already defined above, so a
    # combined request like "explain transformers and give me the
    # latest news on them" still keeps answer=True.

    def _apply_web_research_answer_override(self, result: dict, q: str) -> dict:

        if result.get("web_research") and not any(
            hint in q for hint in self._EXPLANATION_HINTS
        ):

            result["answer"] = False

        return result

    # ----------------------------------------------------------------
    # EXTERNAL ACTION OVERRIDE
    # ----------------------------------------------------------------
    # Same rationale as every override above: "where can I apply for
    # X" / "book me a flight" style requests need a hard keyword safety
    # net, since a miss here means the request gets treated as a plain
    # question and answered with a generic explanation instead of being
    # routed to TaskRouterAgent for a verified destination — or worse,
    # answered in a way that could be misread as the AI having done the
    # thing itself.

    _EXTERNAL_ACTION_HINTS = (
        "where can i apply", "where do i apply", "where can i register",
        "where do i register", "where can i sign up", "where do i sign up",
        "where can i book", "where do i book", "where can i buy",
        "where do i buy", "where can i purchase", "how do i apply for",
        "how do i register for", "how do i sign up for", "official website for",
        "official portal for", "official site for", "book me a", "book a flight",
        "apply for me", "register me for", "sign me up for", "purchase this for me",
        "buy this for me", "where to apply", "where to register",
        "where to sign up", "where to book", "where to buy"
    )

    def _apply_external_action_override(self, result: dict, q: str) -> dict:

        if any(hint in q for hint in self._EXTERNAL_ACTION_HINTS):

            result["external_action"] = True

        return result

    # ----------------------------------------------------------------
    # EXTERNAL ACTION -> ANSWER SUPPRESSION OVERRIDE
    # ----------------------------------------------------------------
    # Same pattern as the diagram/web_research suppression overrides:
    # a pure "where can I apply for a passport" request shouldn't ALSO
    # trigger a generic TutorAgent explanation — the redirect message
    # already covers the request. Reuses _EXPLANATION_HINTS, so a
    # combined request like "explain what AWS certification is and
    # tell me where to register" still keeps answer=True.

    def _apply_external_action_answer_override(self, result: dict, q: str) -> dict:

        if result.get("external_action") and not any(
            hint in q for hint in self._EXPLANATION_HINTS
        ):

            result["answer"] = False

        return result

    # ----------------------------------------------------------------
    # DETERMINISTIC ROUTING
    # ----------------------------------------------------------------
    # Most requests name exactly one thing they want. Each intent
    # "family" below is a small whole-word rule; when exactly ONE family
    # matches (optionally alongside a plain question form for "answer"),
    # the intents are decided here with no LLM call. Zero or several
    # families -> None, and the LLM classifier decides. Deliberately
    # small: anything unclear stays with the LLM.

    _SMALL_TALK_RE = re.compile(
        r"^(?:(?:hi|hello|hey|hiya|yo|thanks|thank you|thx|ok|okay|cool|"
        r"great|nice|awesome|bye|goodbye|good (?:morning|afternoon|"
        r"evening|night))\b[\s,!.]*(?:there|so much|a lot|athena|again)?"
        r"[\s,!.]*)*(?:how are you(?: doing)?|how's it going|what's up|"
        r"who are you|what can you do|what is your name|what's your name)?"
        r"[\s!.?]*$"
    )

    _FAMILY_RES = {
        "quiz": re.compile(
            r"\b(?:quiz(?:zes)?|mcqs?|multiple[- ]choice|practice questions|"
            r"test me|quiz me)\b"
        ),
        "notes": re.compile(r"\bnotes?\b"),
        "comparison": re.compile(
            r"\b(?:compare|comparing|comparison|contrast|difference between|"
            r"differences|similarities|versus|vs\.?)(?=\W|$)"
        ),
        "videos": re.compile(r"\b(?:videos?|youtube)\b"),
        "papers": re.compile(
            r"\b(?:research papers?|papers (?:on|about|for)|arxiv|"
            r"scholarly articles?)\b"
        ),
    }

    _DIAGRAM_ACTION_RE = re.compile(
        r"\b(?:draw|create|generate|make|show me|plot|give|sketch|design|"
        r"build|illustrate|visuali[sz]e)\b"
    )

    # Explicit request to CREATE a new visual ("generate an image of...",
    # "draw an illustration of...", "make an image showing...", "create a
    # flowchart from this"). With an image attached, only this counts as
    # a generation request — merely mentioning "image"/"diagram" is a
    # question ABOUT the attachment.
    # The visual must be the OBJECT being created: up to three words
    # between the verb and the noun, none of them a preposition or a
    # pointer at the attachment — so "make a quiz from this image" and
    # "make this image brighter" are not generation requests.
    _CREATE_VISUAL_RE = re.compile(
        r"\b(?:generate|create|draw|make|produce|render|paint|sketch|design|"
        r"plot|build)\s+"
        r"(?:(?!(?:from|of|about|on|in|using|based|for|with|this|that|these|"
        r"those|it)\b)[\w'-]+[\s,]+){0,3}"
        r"(?:images?|pictures?|illustrations?|drawings?|photos?|art|artwork|"
        r"posters?|diagrams?|flow ?charts?|charts?|graphs?|mind ?maps?|"
        r"visuals?|sketch(?:es)?)\b"
    )

    _ANSWER_FORM_RE = re.compile(
        r"^(?:what|how|why|when|where|who|whom|which|explain|describe|define|"
        r"tell me|teach me|can you|could you|would you|please explain|is|"
        r"are|does|do|did|should|summari[sz]e|give me an? (?:overview|"
        r"summary|explanation|example))\b|\?\s*$"
    )

    _EXPLAIN_TOO_RE = re.compile(
        r"\b(?:explain|describe|what is|what are|tell me about|teach me|"
        r"why|how does|how do|define|with an? examples?)\b"
    )

    _ALL_PDFS_RE = re.compile(
        r"\b(?:all (?:uploaded )?(?:pdfs?|documents)|every pdf|cross pdf|"
        r"combined (?:notes|quiz))\b"
    )

    @staticmethod
    def _intents(**true_flags) -> dict:

        base = {
            "chat": False, "answer": False, "quiz": False, "notes": False,
            "diagram": False, "videos": False, "papers": False,
            "comparison": False, "all_pdfs": False, "web_research": False,
            "external_action": False, "knowledge_source": "general",
            "resource_source": "query"
        }
        base.update(true_flags)

        return base

    def route_deterministically(self, q: str, has_image: bool = False) -> dict | None:
        """
        has_image: the user attached image(s) this turn. Then the request
        is about UNDERSTANDING that image unless it explicitly asks to
        create a new visual (_CREATE_VISUAL_RE).
        """

        # Imported here: diagram_agent is a sibling agent module.
        from agents.diagram_agent import _keyword_type

        if self._SMALL_TALK_RE.match(q):
            return self._intents(chat=True)

        families = [
            name for name, pattern in self._FAMILY_RES.items()
            if pattern.search(q)
        ]

        diagram_type = _keyword_type(q)

        if has_image and not self._CREATE_VISUAL_RE.search(q):
            # "What does this image/diagram show?", "Explain this image",
            # "Analyze this chart" -> image understanding (VisionAgent's
            # description feeds the tutor answer), never generation.
            diagram_type = None

        if diagram_type and (
            self._DIAGRAM_ACTION_RE.search(q)
            or diagram_type == "math_chart"
            or re.match(r"^(?:a |an |the )?(?:flow ?chart|diagram|mind ?map|"
                        r"sequence diagram|chart|graph)\b", q)
        ):
            families.append("diagram")

        if any(hint in q for hint in self._WEB_RESEARCH_HINTS):
            families.append("web_research")

        if any(hint in q for hint in self._EXTERNAL_ACTION_HINTS):
            families.append("external_action")

        all_pdfs = bool(self._ALL_PDFS_RE.search(q))
        explicit_pdf = all_pdfs or self.references_pdf(q)
        source = {
            "knowledge_source": "pdf" if explicit_pdf else "general",
            "resource_source": "pdf" if explicit_pdf else "query",
            "all_pdfs": all_pdfs,
        }

        if len(families) > 1:
            return None

        if len(families) == 1:

            # "explain X and give a diagram" wants an explanation TOO —
            # a combination, so let the LLM decide. Comparisons are
            # explanatory by nature ("what are the differences...").
            if families[0] != "comparison" and self._EXPLAIN_TOO_RE.search(q):
                return None

            return self._intents(**{families[0]: True}, **source)

        if self._ANSWER_FORM_RE.search(q):

            # A question that also mentions a visual ("teach me X with a
            # flowchart") is a combination — the LLM decides.
            if diagram_type:
                return None

            return self._intents(answer=True, **source)

        if has_image:
            # "this image?", "analyze it" — about the attachment.
            return self._intents(answer=True, **source)

        return None

    def _apply_overrides(self, result: dict, q: str, has_image: bool = False) -> dict:
        """Runs all hard keyword safety nets in one call so every
        return path in classify() only needs one call instead of
        remembering to chain each one individually."""

        result = self._apply_video_override(result, q)
        if has_image and not self._CREATE_VISUAL_RE.search(q):
            # A question about the attached image is not a request for a
            # new picture, whatever words it uses ("image", "diagram").
            result["diagram"] = False
            if not any(result.get(k) for k in (
                "answer", "quiz", "notes", "comparison", "videos", "papers",
                "web_research", "external_action", "chat"
            )):
                result["answer"] = True
        else:
            result = self._apply_diagram_override(result, q)
        result = self._apply_diagram_answer_override(result, q)
        result = self._apply_knowledge_source_override(result, q)
        result = self._apply_web_research_override(result, q)
        result = self._apply_web_research_answer_override(result, q)
        result = self._apply_external_action_override(result, q)
        result = self._apply_external_action_answer_override(result, q)

        return result

    @traceable(
        name="IntentClassifier.classify"
    )
    def classify(
        self,
        query: str,
        has_image: bool = False
    ):

        q = query.lower().strip()

        # =====================================
        # DETERMINISTIC ROUTING FIRST
        # =====================================
        # Clear requests ("make notes on X", "quiz me", "compare X and
        # Y", "draw a flowchart", "how does X work?", "hi") are decided
        # by rules — no LLM call. Only genuinely ambiguous or combined
        # requests fall through to the LLM classifier below.

        routed = self.route_deterministically(q, has_image=has_image)

        if routed is not None:

            self.last_route = "deterministic"
            return self._apply_overrides(routed, q, has_image)

        self.last_route = "llm"

        # =====================================
        # LLM CLASSIFICATION (ambiguous requests only)
        # =====================================

        prompt = f"""
Classify a student's request to an AI tutor. Return ONLY one JSON object:

{{"chat": bool, "answer": bool, "quiz": bool, "notes": bool,
 "diagram": bool, "videos": bool, "papers": bool, "comparison": bool,
 "all_pdfs": bool, "web_research": bool, "external_action": bool,
 "knowledge_source": "general" | "pdf" | "hybrid",
 "resource_source": "query" | "pdf"}}

Several intents may be true at once.

INTENTS
- chat: small talk only (greetings, thanks, "who are you").
- answer: explain / answer a question; also follow-ups like "why?",
  "how?", "explain more", "give an example", "advantages?".
- quiz: quiz / MCQs / practice questions.
- notes: study notes.
- diagram: any VISUAL — flowchart, diagram, mind map, chart, graph,
  plot of a function, picture/image/illustration.
- videos: YouTube / video recommendations.
- papers: research papers.
- comparison: compare / differences / similarities between things.
- all_pdfs: the request covers ALL uploaded PDFs ("all pdfs",
  "every pdf", "combined notes").
- web_research: needs CURRENT information (latest news, recent
  developments, "as of today").
- external_action: the user must go DO something elsewhere (apply,
  register, book, buy): "where can I apply for X", "book me a flight".

RULES
- A request ONLY for a visual, current info, or an external action has
  answer=false. Keep answer=true only when an explanation is ALSO asked
  for ("explain photosynthesis and give a diagram").
- knowledge_source: "pdf" if the user refers to their uploaded
  PDF/document/file ("from the pdf", "according to the document");
  "hybrid" if they want the PDF plus outside knowledge ("expand the pdf
  notes with examples"); otherwise "general".
- resource_source: "pdf" if videos/papers/notes should be based on the
  uploaded PDF's topics, else "query".

EXAMPLES
"explain neural networks and give videos" -> answer, videos
"give youtube videos related to uploaded pdf" -> videos; knowledge_source pdf; resource_source pdf
"explain uploaded pdf and add examples" -> answer; knowledge_source hybrid; resource_source pdf
"what's the latest news on AI regulation" -> web_research only
"explain what AWS certification is and tell me where to register" -> answer, external_action
"compare adaptive modulation from all uploaded pdfs" -> comparison, all_pdfs; knowledge_source pdf

{"IMAGE ATTACHED: the student attached an image this turn. Questions about it ('what does this show', 'explain this diagram') are answer=true, diagram=false. Only an explicit request to create a NEW visual sets diagram=true." if has_image else ""}

REQUEST:
{query}
"""

        try:

            response = route(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                purpose="classify"
            )

            # Take the JSON object even if the model wrapped it in
            # fences or a sentence.
            match = re.search(r"\{.*\}", response, re.DOTALL)

            intents = json.loads(
                match.group(0) if match else response
            )

            defaults = {
                "chat": False,
                "answer": False,
                "quiz": False,
                "notes": False,
                "diagram": False,
                "videos": False,
                "papers": False,
                "comparison": False,
                "all_pdfs": False,
                "web_research": False,
                "external_action": False,
                "knowledge_source": "general",
                "resource_source": "query"
            }

            defaults.update(
                intents
            )

            return self._apply_overrides(defaults, q, has_image)

        except LLMQuotaExhaustedError:

            # Daily quota: the rest of this turn can't succeed either —
            # fail now instead of falling back and calling again.
            raise

        except Exception as e:

            print(
                f"IntentClassifier Error: {e}"
            )

            return self._apply_overrides({
                "chat": False,
                "answer": True,
                "quiz": False,
                "notes": False,
                "diagram": False,
                "videos": False,
                "papers": False,
                "comparison": False,
                "all_pdfs": False,
                "web_research": False,
                "external_action": False,
                "knowledge_source": "general",
                "resource_source": "query"
            }, q, has_image)