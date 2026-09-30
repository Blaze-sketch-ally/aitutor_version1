import json
import os

from langsmith import traceable

from models.config import get_vision_model
from models.errors import LLMServiceError
from models.router import route_vision
from schemas.attachment import VisionAnalysisResult


class VisionAgent:
    """
    General-purpose image-understanding agent — NOT specialized per
    image category (no MathImageAgent/CircuitImageAgent/etc). One
    prompt asks the vision model to determine what kind of image it's
    looking at and describe it usefully; the caller's free-text
    instruction (if any) steers what the description focuses on, but
    this agent does not itself fulfill the instruction (e.g. it will
    not generate a quiz) — routing the resulting understanding to
    TutorAgent/QuizAgent/NotesAgent/etc. is a later step. This keeps
    VisionAgent's only responsibility "understand the image(s)".

    Follows the same conventions as every other agent in this
    codebase: provider/model set in __init__, one @traceable public
    method, try/except with a safe fallback rather than raising.
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
    ):
        self.provider = provider or os.getenv(
            "VISION_MODEL_PROVIDER", "groq"
        )
        self.model = model or get_vision_model()

    # ==================================================
    # PUBLIC ENTRY POINT
    # ==================================================

    @traceable(
        name="VisionAgent.analyze_images"
    )
    def analyze_images(
        self,
        images: list[bytes],
        image_mime_types: list[str] | None = None,
        instruction: str = "",
        context: str = "",
        history_text: str = "",
        summary: str = "",
    ) -> dict:
        """
        images: raw validated image bytes (see
        services/attachment_service.py) — never filesystem paths, so
        this method (and its LangSmith trace) never needs to handle or
        expose a server-side path.

        Returns a dict matching schemas.attachment.VisionAnalysisResult.
        On any failure, returns a safe fallback with confidence 0.0
        and a plain-language explanation instead of raising, matching
        every other agent's fail-soft convention.
        """

        image_count = len(images)

        if image_count == 0:
            return VisionAnalysisResult(
                description="No image was provided to analyze.",
                instruction=instruction or None,
                image_count=0,
                model_used=self.model,
            ).model_dump()

        prompt = self._build_prompt(
            instruction=instruction,
            context=context,
            history_text=history_text,
            summary=summary,
            image_count=image_count,
        )

        try:
            raw = route_vision(
                prompt=prompt,
                images=images,
                image_mime_types=image_mime_types,
                provider=self.provider,
                model=self.model,
            )

        except LLMServiceError:

            # Provider failure (model retired, auth, rate limit): surface
            # it as a real error instead of passing an apology text on to
            # the tutor as if it were the image's description.
            raise

        except Exception as e:

            print(f"VisionAgent model call failed: {e}")

            return VisionAnalysisResult(
                description=(
                    "Sorry, I couldn't analyze this image right now. "
                    "The vision model may be unavailable, or the "
                    "image could not be processed."
                ),
                confidence=0.0,
                instruction=instruction or None,
                image_count=image_count,
                model_used=self.model,
            ).model_dump()

        try:
            data = self._extract_json(raw)

            result = VisionAnalysisResult(
                description=data.get(
                    "description",
                    "I could not generate a description for this image."
                ),
                content_type=data.get("content_type", "unknown"),
                detected_text=data.get("detected_text") or None,
                concepts=data.get("concepts") or [],
                objects=data.get("objects") or [],
                domain=data.get("domain") or None,
                confidence=float(data.get("confidence", 0.5) or 0.0),
                instruction=instruction or None,
                image_count=image_count,
                model_used=self.model,
            )

        except Exception as e:

            # The model responded but not in the requested JSON shape
            # — fall back to using its raw text as the description
            # rather than discarding a possibly-useful answer.
            print(f"VisionAgent response parsing failed: {e}")

            result = VisionAnalysisResult(
                description=(
                    raw.strip() if raw and raw.strip()
                    else "I could not reliably understand this image."
                ),
                confidence=0.3 if raw and raw.strip() else 0.0,
                instruction=instruction or None,
                image_count=image_count,
                model_used=self.model,
                raw_response=raw,
            )

        return result.model_dump()

    # ==================================================
    # PROMPT
    # ==================================================

    def _build_prompt(
        self,
        instruction: str,
        context: str,
        history_text: str,
        summary: str,
        image_count: int,
    ) -> str:

        instruction_block = (
            instruction.strip()
            if instruction and instruction.strip()
            else (
                "No specific instruction was given — provide a useful "
                "general explanation of the image(s): what they show, "
                "the main subject, key elements/relationships, and an "
                "educational explanation if the content is "
                "educational."
            )
        )

        plural_note = (
            f"You are given {image_count} images — consider them "
            "together (e.g. compare them, summarize across all of "
            "them) unless the instruction says otherwise.\n"
            if image_count > 1 else ""
        )

        return f"""
Your are Athena, an AI Tutor's general-purpose vision component. You can be
shown ANY kind of image — textbook pages, book screenshots, handwritten
notes, scanned documents, mathematical problems/equations, graphs,
charts, tables, diagrams, flowcharts, circuit/electronics/engineering
diagrams, scientific diagrams, chemistry structures, physics diagrams,
geometry, maps, code screenshots, terminal screenshots, error
screenshots, presentation slides, whiteboard photos, website or
application screenshots, newspaper/article screenshots, photographs,
technical drawings, architecture diagrams, or any other visually
understandable image. Determine what kind of image this is yourself —
never ask the user to specify it.

{plural_note}
RULES:
- Do not fabricate details you cannot actually determine from the
  image. If it is unclear, low quality, or ambiguous, say so
  explicitly instead of guessing.
- If there is readable text in the image, transcribe the meaningful
  parts into detected_text (not necessarily every character).
- Keep "description" genuinely useful on its own, since it may be
  shown to the user directly if they uploaded the image with no
  question at all.
- Use the user instruction to decide what to emphasize in the
  description, but do not attempt to perform tasks like "make a quiz"
  or "write notes" yourself — just describe/explain what the image
  contains; a separate step will use your description for that.

==================================================
CONVERSATION SUMMARY
==================================================
{summary}

==================================================
CONVERSATION HISTORY
==================================================
{history_text}

==================================================
ADDITIONAL CONTEXT (e.g. related PDF excerpts, if any)
==================================================
{context}

==================================================
USER INSTRUCTION
==================================================
{instruction_block}

==================================================
OUTPUT FORMAT — RETURN ONLY THIS JSON, NOTHING ELSE
==================================================
{{
  "description": "Thorough, useful description/explanation of the image(s), written for a student.",
  "content_type": "e.g. textbook_page, handwritten_notes, diagram, chart, table, code_screenshot, terminal_screenshot, photograph, circuit_diagram, math_problem, map, slide, whiteboard, other",
  "detected_text": "Meaningful text visible in the image, or null if none/not legible.",
  "concepts": ["key concept 1", "key concept 2"],
  "objects": ["notable visible element 1", "notable visible element 2"],
  "domain": "e.g. computer_science, mathematics, physics, chemistry, biology, electronics, general, etc.",
  "confidence": 0.0
}}

RULES FOR THE JSON:
- confidence is 0.0-1.0: your genuine confidence in this analysis
- Return ONLY valid JSON, no markdown fences, no explanation outside it
"""

    # ==================================================
    # JSON PARSING HELPERS
    # (same approach as DiagramAgent._extract_json/_strip_fences —
    # small models frequently wrap JSON in prose or fences despite
    # instructions not to)
    # ==================================================

    @staticmethod
    def _strip_fences(text: str) -> str:

        cleaned = text.strip()

        if cleaned.startswith("```"):

            cleaned = cleaned.strip("`")

            first_line, _, rest = cleaned.partition("\n")

            if first_line.strip().isalpha():
                cleaned = rest

        return cleaned.strip()

    @classmethod
    def _extract_json(cls, text: str) -> dict:

        cleaned = cls._strip_fences(text or "")

        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            pass

        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start:end + 1])

        raise ValueError("No JSON object found in vision model response.")
