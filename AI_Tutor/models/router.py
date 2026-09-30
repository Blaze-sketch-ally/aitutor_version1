from models.config import get_task_profile, get_text_model, get_vision_model
from models.groq_client import generate as groq_generate
from models.groq_client import generate_stream as groq_generate_stream
from models.hf_client import generate as hf_generate
from models.vision_client import generate_vision as groq_generate_vision


def _groq_kwargs(model: str | None, purpose: str | None) -> dict:
    """
    Model + generation settings for a Groq call. An explicit `model`
    always wins; otherwise the task profile for `purpose` picks the
    model role (TEXT_MODEL / FAST_MODEL — models/config.py). Extra
    settings are only included when set, so purpose-less calls behave
    exactly as before.
    """

    profile = get_task_profile(purpose)
    model = model or profile["model"]

    kwargs = {"model": model}

    # reasoning_effort is a gpt-oss parameter; other models reject it.
    if profile["reasoning_effort"] and model.startswith("openai/gpt-oss"):
        kwargs["reasoning_effort"] = profile["reasoning_effort"]

    if profile["max_tokens"]:
        kwargs["max_tokens"] = profile["max_tokens"]

    if purpose:
        kwargs["purpose"] = purpose

    return kwargs


def route(
    prompt: str,
    provider: str = "groq",
    model: str | None = None,
    purpose: str | None = None
):
    """
    Routes requests to the selected model provider.

    purpose: task name from models/config.py TASK_PROFILES ("classify",
    "answer", "notes", ...). Decides model role, reasoning effort and
    output budget; None keeps the plain main-model call.
    """

    provider = provider.lower()

    if provider == "groq":

        return groq_generate(
            prompt=prompt,
            **_groq_kwargs(model, purpose)
        )

    elif provider == "hf":

        return hf_generate(
            prompt=prompt,
            **({"model": model} if model else {})
        )

    else:
        raise ValueError(
            f"Unsupported provider: {provider}"
        )


def route_vision(
    prompt: str,
    images: list,
    image_mime_types: list | None = None,
    provider: str = "groq",
    model: str | None = None
):
    """
    Multimodal counterpart to route() — routes an image+text prompt to
    a configured vision-capable model.

    Only "groq" is wired today since that's the only provider in this
    codebase with a vision-capable model configured, but the dispatch
    shape matches route()/route_stream() exactly, so adding another
    vision provider later means adding a branch here — not changing
    VisionAgent or anything upstream of it.
    """

    provider = provider.lower()

    if provider == "groq":

        if model is None:
            model = get_vision_model()

        return groq_generate_vision(
            prompt=prompt,
            images=images,
            image_mime_types=image_mime_types,
            model=model
        )

    else:
        raise ValueError(
            f"Unsupported vision provider: {provider}"
        )


def route_stream(
    prompt: str,
    provider: str = "groq",
    model: str | None = None,
    purpose: str | None = None
):
    """
    Streaming counterpart to route() — yields text chunks as they
    arrive instead of returning a single complete string.

    Only implemented for "groq" for now, since that's the only
    provider used for user-facing text generation (ChatAgent/
    TutorAgent) in this codebase today. "hf" falls back to a
    single-chunk "stream" (the whole response yielded at once) rather
    than raising, so callers built around route_stream() don't need a
    separate code path if hf is ever selected — it just won't feel
    incremental.
    """

    provider = provider.lower()

    if provider == "groq":

        yield from groq_generate_stream(
            prompt=prompt,
            **_groq_kwargs(model, purpose)
        )

    elif provider == "hf":

        yield hf_generate(
            prompt=prompt,
            **({"model": model} if model else {})
        )

    else:
        raise ValueError(
            f"Unsupported provider: {provider}"
        )