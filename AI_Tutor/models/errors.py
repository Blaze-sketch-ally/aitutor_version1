import re


class ServiceUnavailableError(RuntimeError):
    """
    Base for failures of a backing service (model provider, vector
    database) that the user should see as a temporary error rather than
    as an answer. str(e) is the server-side diagnostic (log it);
    e.user_message is safe to return to clients. main.py maps every
    subclass to HTTP 503; the SSE stream sends user_message.
    """

    default_user_message = (
        "A service needed for this request is temporarily unavailable. "
        "Please try again in a moment."
    )

    def __init__(self, message: str, user_message: str | None = None):

        super().__init__(message)

        self.user_message = user_message or self.default_user_message


class RetrievalError(ServiceUnavailableError):
    """
    The vector/database search itself FAILED — distinct from a search
    that succeeded and found nothing relevant (which is not an error).
    Never answer an explicit PDF question as if retrieval had worked.
    """

    default_user_message = (
        "I couldn't search your selected PDF right now because of a "
        "temporary problem. Please try again in a moment."
    )


class LLMServiceError(ServiceUnavailableError):
    """
    Raised when a model provider call fails (model retired, auth,
    rate limit, network, empty completion).

    str(e) is the detailed, server-side diagnostic (model id, provider
    error type/status) — log it, never show it to users.
    e.user_message is a short, secret-free message that is safe to
    return in an API response.

    Subclasses RuntimeError so existing `except RuntimeError` /
    `except Exception` handlers keep working.
    """

    default_user_message = (
        "The AI model could not generate a response right now. "
        "Please try again in a moment."
    )


class LLMQuotaExhaustedError(LLMServiceError):
    """
    A DAILY provider quota (tokens/requests per day) is used up. Retrying
    within the request can't succeed, so this is never retried and must
    not be swallowed by fallback logic in helper steps (classifier,
    resolver, summary) — the whole turn should fail fast.
    """


def is_daily_quota_error(e: Exception) -> bool:

    return getattr(e, "status_code", None) == 429 and bool(
        re.search(r"per day|\(TPD\)|\(RPD\)", str(e))
    )


def describe_provider_error(e: Exception) -> str:
    """
    Maps a provider SDK exception to a user-safe message. Looks at the
    HTTP status only — never echoes the raw provider message, which
    can include request details.
    """

    status = getattr(e, "status_code", None)

    if status in (401, 403):
        return (
            "The AI model service rejected the server's credentials. "
            "Please contact the administrator."
        )

    if status == 404 or (status == 400 and "decommission" in str(e).lower()):
        return (
            "The configured AI model is unavailable. "
            "Please contact the administrator."
        )

    # Daily quotas (tokens/requests per day) don't clear in "a moment".
    # Only the quota kind is inspected, never echoed.
    if is_daily_quota_error(e):
        return (
            "The AI service's daily usage limit has been reached. "
            "Please try again later."
        )

    if status == 429:
        return (
            "The AI model is receiving too many requests right now. "
            "Please wait a moment and try again."
        )

    if status == 413:
        return (
            "This request is too large for the AI model. "
            "Try a shorter question or fewer selected PDFs."
        )

    if status is not None and status >= 500:
        return (
            "The AI model service is temporarily unavailable. "
            "Please try again in a moment."
        )

    return (
        "The AI model could not generate a response right now. "
        "Please try again in a moment."
    )
