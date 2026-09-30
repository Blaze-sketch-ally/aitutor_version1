import base64
import time
import os

from groq import Groq
from dotenv import load_dotenv

from models.config import get_groq_api_key, get_vision_model
from models.errors import LLMServiceError, describe_provider_error
from models.metrics import record_llm_call

load_dotenv()

# API key via models/config.py (canonical env var: GROQ_APIKEY).
_client = Groq(api_key=get_groq_api_key())

# Vision model id comes from models/config.py (VISION_MODEL env var).


def _to_data_uri(image_bytes: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def generate_vision(
    prompt: str,
    images: list[bytes],
    image_mime_types: list[str] | None = None,
    model: str | None = None,
    temperature: float = 0.2,
):
    """
    Sends one text prompt plus one or more images to a Groq
    vision-capable chat model, using the same OpenAI-compatible
    `image_url` content-block format as models/groq_client.py's
    plain-text `generate()` uses for `content`, just multimodal.

    Deliberately bypasses models/router.py's text-only route()
    instead of overloading it — this mirrors the precedent
    VideoSummaryAgent already set with its own raw groq.Groq() client
    for Whisper transcription. models/router.py and
    models/groq_client.py are untouched by this file, so every
    existing text-only agent (IntentClassifier, TutorAgent, ChatAgent,
    etc.) is completely unaffected by adding vision support.
    """

    if not images:
        raise ValueError("generate_vision() requires at least one image.")

    model = model or get_vision_model()
    mime_types = image_mime_types or ["image/png"] * len(images)

    content = [{"type": "text", "text": prompt}]

    for image_bytes, mime_type in zip(images, mime_types):
        content.append({
            "type": "image_url",
            "image_url": {
                "url": _to_data_uri(image_bytes, mime_type or "image/png")
            }
        })

    started = time.perf_counter()

    try:

        response = _client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": content
                }
            ],
            temperature=temperature,
        )

    except Exception as e:

        error = LLMServiceError(
            f"Groq generate_vision() failed (model={model}, "
            f"error={type(e).__name__}, "
            f"status={getattr(e, 'status_code', None)}): {e}",
            user_message=describe_provider_error(e)
        )
        print(f"LLM ERROR: {error}")
        raise error from e

    usage = getattr(response, "usage", None)
    record_llm_call(
        model,
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        (time.perf_counter() - started) * 1000,
        kind="vision"
    )

    return response.choices[0].message.content
