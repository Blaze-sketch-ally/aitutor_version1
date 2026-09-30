import random
import re
import time

from groq import APIConnectionError, APITimeoutError, Groq
from dotenv import load_dotenv

from models.config import get_groq_api_key, get_text_model
from models.errors import (
    LLMQuotaExhaustedError,
    LLMServiceError,
    describe_provider_error,
    is_daily_quota_error,
)
from models.metrics import record_llm_call

load_dotenv()

# max_retries=0: the SDK's own silent retries are disabled so the policy
# below is the only one (see _retry_delay) — no hidden retry storms.
client = Groq(
    api_key=get_groq_api_key(),
    max_retries=0
)

# Every agent sends one big prompt "template" (instructions + CONVERSATION
# SUMMARY / HISTORY / PDF CONTEXT sections) as a single user message.
# Instruction-tuned reasoning models (gpt-oss) otherwise treat it as a
# document to continue and echo those section headings back into the
# student-facing reply. This keeps replies to the actual response
# without changing any agent's prompt.
SYSTEM_PROMPT = (
    "You are the answer-writing component of an AI tutor app. The user "
    "message is a prompt template: instructions plus reference sections "
    "(conversation summary, history, PDF context, etc.). Reply with ONLY "
    "the final response to show the student. Do not reproduce, list, or "
    "summarize the template's sections or headings unless the "
    "instructions ask for them."
)


def _messages(prompt: str) -> list[dict]:

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]


# =====================================
# RATE-LIMIT / RETRY POLICY
# =====================================
# - Per-minute limits (TPM/RPM, HTTP 429): wait what Groq says
#   ("try again in 3.4s" / Retry-After), capped, with jitter, at most
#   MAX_RATE_LIMIT_RETRIES times. Longer waits fail immediately.
# - Daily quota (TPD/RPD): never retried; the model is marked blocked
#   for a short cool-down so the rest of this turn (and concurrent
#   turns) fail instantly instead of each paying for a doomed request.
# - Connection errors / 5xx: one short retry.
# - Any other 4xx (bad request, auth, model not found, too large): no
#   retry.

MAX_RATE_LIMIT_WAIT_S = 10.0
MAX_RATE_LIMIT_RETRIES = 2
MAX_TRANSIENT_RETRIES = 1
QUOTA_COOLDOWN_CAP_S = 120.0

_quota_blocked_until: dict[str, float] = {}

_TRY_AGAIN_RE = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?")


def _suggested_wait(e: Exception) -> float | None:

    response = getattr(e, "response", None)
    headers = getattr(response, "headers", None) or {}

    try:
        retry_after = headers.get("retry-after")
        if retry_after:
            return float(retry_after)
    except (TypeError, ValueError, AttributeError):
        pass

    match = _TRY_AGAIN_RE.search(str(e))

    if match and any(match.groups()):
        hours, minutes, seconds = match.groups()
        return (
            int(hours or 0) * 3600
            + int(minutes or 0) * 60
            + float(seconds or 0)
        )

    return None


def _retry_delay(e: Exception, rate_limit_retries: int, transient_retries: int) -> float | None:
    """Seconds to wait before retrying, or None to fail now."""

    if is_daily_quota_error(e):
        return None

    status = getattr(e, "status_code", None)

    if status == 429:

        if rate_limit_retries >= MAX_RATE_LIMIT_RETRIES:
            return None

        wait = _suggested_wait(e)
        wait = 1.0 * (2 ** rate_limit_retries) if wait is None else wait

        if wait > MAX_RATE_LIMIT_WAIT_S:
            return None

        return wait + random.uniform(0.1, 0.6)

    transient = isinstance(e, (APIConnectionError, APITimeoutError)) or (
        status is not None and status >= 500
    )

    if transient and transient_retries < MAX_TRANSIENT_RETRIES:
        return 0.5 + random.uniform(0, 0.5)

    return None


def _check_quota_block(model: str):

    blocked_until = _quota_blocked_until.get(model)

    if blocked_until and time.monotonic() < blocked_until:
        raise LLMQuotaExhaustedError(
            f"Groq daily quota for {model} recently exhausted; "
            f"not calling the provider again for "
            f"{blocked_until - time.monotonic():.0f}s.",
            user_message=(
                "The AI service's daily usage limit has been reached. "
                "Please try again later."
            )
        )


def _to_service_error(e: Exception, model: str, where: str) -> LLMServiceError:

    detail = (
        f"Groq {where} failed (model={model}, error={type(e).__name__}, "
        f"status={getattr(e, 'status_code', None)}): {e}"
    )

    if is_daily_quota_error(e):

        cooldown = min(_suggested_wait(e) or 60.0, QUOTA_COOLDOWN_CAP_S)
        _quota_blocked_until[model] = time.monotonic() + cooldown

        error = LLMQuotaExhaustedError(detail, user_message=describe_provider_error(e))

    else:

        error = LLMServiceError(detail, user_message=describe_provider_error(e))

    print(f"LLM ERROR: {error}")

    return error


def _completion_kwargs(reasoning_effort: str | None, max_tokens: int | None) -> dict:

    kwargs = {}

    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort

    if max_tokens:
        kwargs["max_completion_tokens"] = max_tokens

    return kwargs


def _call_groq(
    prompt: str,
    model: str,
    temperature: float,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    purpose: str | None = None
):

    started = time.perf_counter()

    try:

        response = client.chat.completions.create(
            model=model,
            messages=_messages(prompt),
            temperature=temperature,
            **_completion_kwargs(reasoning_effort, max_tokens)
        )

    except Exception:

        record_llm_call(
            model, None, None, (time.perf_counter() - started) * 1000,
            purpose=purpose, ok=False
        )
        raise

    usage = getattr(response, "usage", None)
    record_llm_call(
        model,
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        (time.perf_counter() - started) * 1000,
        purpose=purpose
    )

    choice = response.choices[0]

    content = choice.message.content
    finish_reason = getattr(choice, "finish_reason", None)

    return content, finish_reason


def generate(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    max_retries: int = 1,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    purpose: str | None = None
):
    """
    Generate text using Groq models.

    Every caller in this codebase funnels through this function (via
    models/router.py), so the retry policy above and the empty-content
    check below apply everywhere.

    - Provider errors follow _retry_delay() (bounded; daily quota never
      retried).
    - Empty/None content is retried `max_retries` times, then raises
      LLMServiceError with diagnostic context instead of returning "".
    """

    model = model or get_text_model()

    _check_quota_block(model)

    rate_limit_retries = 0
    transient_retries = 0
    empty_retries = 0
    last_finish_reason = None

    while True:

        try:

            content, finish_reason = _call_groq(
                prompt=prompt,
                model=model,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                purpose=purpose
            )

        except Exception as e:

            delay = _retry_delay(e, rate_limit_retries, transient_retries)

            if delay is None:
                raise _to_service_error(e, model, "generate()") from e

            if getattr(e, "status_code", None) == 429:
                rate_limit_retries += 1
            else:
                transient_retries += 1

            print(
                f"Groq call failed ({type(e).__name__}, "
                f"status={getattr(e, 'status_code', None)}); "
                f"retrying in {delay:.1f}s"
            )

            time.sleep(delay)

            continue

        last_finish_reason = finish_reason

        if content and content.strip():

            return content

        if empty_retries < max_retries:

            empty_retries += 1

            print(
                f"Groq returned empty content (finish_reason="
                f"{finish_reason}), retrying..."
            )

            time.sleep(0.5)

            continue

        break

    # Still empty. Raise instead of returning "" so the failure is loud
    # and diagnosable at the source.
    error = LLMServiceError(
        f"Groq generate() returned empty content after "
        f"{empty_retries + 1} attempt(s) "
        f"(model={model}, finish_reason={last_finish_reason}, "
        f"prompt_length={len(prompt)} chars)."
    )
    print(f"LLM ERROR: {error}")
    raise error


def generate_stream(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    purpose: str | None = None
):
    """
    Streaming counterpart to generate() — yields text chunks as they
    arrive instead of waiting for the full completion.

    Only used for final user-facing text (answer/chat replies). Callers
    that need the FULL string first (JSON parsing etc.) must keep using
    generate()/route().

    Opening the stream follows the same retry policy as generate(); once
    tokens have been sent there is no retry (it would duplicate output).
    """

    model = model or get_text_model()

    _check_quota_block(model)

    started = time.perf_counter()
    usage = None
    rate_limit_retries = 0
    transient_retries = 0

    while True:

        try:

            stream = client.chat.completions.create(
                model=model,
                messages=_messages(prompt),
                temperature=temperature,
                stream=True,
                **_completion_kwargs(reasoning_effort, max_tokens)
            )

            break

        except Exception as e:

            delay = _retry_delay(e, rate_limit_retries, transient_retries)

            if delay is None:
                record_llm_call(
                    model, None, None, (time.perf_counter() - started) * 1000,
                    kind="stream", purpose=purpose, ok=False
                )
                raise _to_service_error(e, model, "generate_stream()") from e

            if getattr(e, "status_code", None) == 429:
                rate_limit_retries += 1
            else:
                transient_retries += 1

            time.sleep(delay)

    try:

        for chunk in stream:

            # Groq reports usage on the final chunk (x_groq.usage).
            x_groq = getattr(chunk, "x_groq", None)
            if x_groq is not None and getattr(x_groq, "usage", None):
                usage = x_groq.usage

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            content = getattr(delta, "content", None)

            if content:

                yield content

        record_llm_call(
            model,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            (time.perf_counter() - started) * 1000,
            kind="stream",
            purpose=purpose
        )

    except LLMServiceError:
        raise

    except Exception as e:

        raise _to_service_error(e, model, "generate_stream()") from e
