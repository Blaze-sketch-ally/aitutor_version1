import os

from dotenv import load_dotenv

load_dotenv()

# =====================================
# CANONICAL MODEL CONFIGURATION
# =====================================
# The ONLY place model ids live. Agents default to model=None, and
# models/router.py resolves None to these at call time, so changing a
# model is an env-var change (TEXT_MODEL / VISION_MODEL), not a code
# search. Read lazily (functions, not module constants) so an env
# change or a test's patched env is picked up without re-importing.
#
# Defaults are models verified live against this project's Groq
# account (2026-09-29). Groq retires models regularly — when a call
# fails with a "model not found / decommissioned" error, check
# client.models.list() and update the env var.

DEFAULT_TEXT_MODEL = "openai/gpt-oss-120b"

# Must accept image_url content blocks — gpt-oss models do not.
DEFAULT_VISION_MODEL = "qwen/qwen3.8-27b"


# =====================================
# GROQ API KEY
# =====================================
# CANONICAL name: GROQ_APIKEY (used by every working client, .env,
# .env.example and render.yaml). GROQ_API_KEY — the Groq SDK's own
# default name, which older video/Whisper code read — is accepted as a
# deprecated fallback so a deployment that only sets that name keeps
# working; it logs a warning so it can be renamed.

CANONICAL_GROQ_KEY_VAR = "GROQ_APIKEY"
DEPRECATED_GROQ_KEY_VAR = "GROQ_API_KEY"

_warned_deprecated_groq_key = False


def get_groq_api_key() -> str | None:

    global _warned_deprecated_groq_key

    key = os.getenv(CANONICAL_GROQ_KEY_VAR)

    if key:
        return key

    key = os.getenv(DEPRECATED_GROQ_KEY_VAR)

    if key and not _warned_deprecated_groq_key:
        print(
            f"WARNING: using deprecated env var {DEPRECATED_GROQ_KEY_VAR}; "
            f"rename it to {CANONICAL_GROQ_KEY_VAR}."
        )
        _warned_deprecated_groq_key = True

    return key or None


def get_text_model() -> str:

    return os.getenv("TEXT_MODEL") or DEFAULT_TEXT_MODEL


# =====================================
# MODEL ROLES + TASK PROFILES
# =====================================
# TEXT_MODEL  — everything the student reads (answers, notes, quizzes,
#               comparisons, diagrams, chat).
# FAST_MODEL  — small internal steps whose output the student never
#               sees directly: ambiguous-intent classification, follow-up
#               query rewriting, conversation-memory summaries, short
#               keyword/prompt extraction. On Groq each model has its own
#               rate limits, so this also moves that traffic off the main
#               model's daily token quota.
# VISION_MODEL — image understanding (see get_vision_model()).
#
# Each task has: model role, reasoning effort (gpt-oss "reasoning
# tokens" count toward the quota; "low" is plenty for routing/extraction)
# and an output budget. The budget covers reasoning + visible output,
# so it is set well above the typical sizes measured in profiling —
# it is a runaway guard, not a length target.

DEFAULT_FAST_MODEL = "openai/gpt-oss-20b"


def get_fast_model() -> str:

    return os.getenv("FAST_MODEL") or DEFAULT_FAST_MODEL


TASK_PROFILES = {
    # internal / fast
    "classify":   {"role": "fast", "reasoning_effort": "low", "max_tokens": 1024},
    "resolve":    {"role": "fast", "reasoning_effort": "low", "max_tokens": 1024},
    "summarize":  {"role": "fast", "reasoning_effort": "low", "max_tokens": 1500},
    "extract":    {"role": "fast", "reasoning_effort": "low", "max_tokens": 1024},
    # student-facing
    "chat":       {"role": "text", "reasoning_effort": "low", "max_tokens": 2048},
    "answer":     {"role": "text", "reasoning_effort": None, "max_tokens": 6144},
    "notes":      {"role": "text", "reasoning_effort": None, "max_tokens": 8192},
    "quiz":       {"role": "text", "reasoning_effort": None, "max_tokens": 8192},
    "comparison": {"role": "text", "reasoning_effort": None, "max_tokens": 6144},
    "diagram":    {"role": "text", "reasoning_effort": None, "max_tokens": 4096},
    "chart":      {"role": "text", "reasoning_effort": "low", "max_tokens": 2048},
}


def get_task_profile(purpose: str | None) -> dict:
    """
    Model + generation settings for a task. Unknown/None purpose keeps
    the old behaviour: main text model, provider defaults.
    """

    profile = TASK_PROFILES.get(purpose or "", {})

    model = (
        get_fast_model() if profile.get("role") == "fast" else get_text_model()
    )

    return {
        "model": model,
        "reasoning_effort": profile.get("reasoning_effort"),
        "max_tokens": profile.get("max_tokens"),
    }


def get_vision_model() -> str:

    return os.getenv("VISION_MODEL") or DEFAULT_VISION_MODEL
