"""
Per-request performance metrics: LLM calls (caller, model, exact token
usage from the provider, latency), retrieval/database calls and total
latency. One "PERF" line is logged per chat request.

Never records prompt/response text or document content — only counts,
sizes and timings.

Usage (request boundary, see services/chat_api_service.py):

    metrics = RequestMetrics("chat")
    with metrics.active():
        ...                      # everything inside is attributed
    metrics.finish()             # logs + returns the summary dict

Anything recorded while no request is active is ignored, so agents and
tests work unchanged outside a request.
"""

import contextvars
import inspect
import json
import time
from collections import deque
from contextlib import contextmanager

_CURRENT: contextvars.ContextVar = contextvars.ContextVar(
    "request_metrics", default=None
)

# Most recent finished requests, for profiling scripts/tests.
RECENT = deque(maxlen=50)


def _caller_label() -> str:
    """First stack frame outside models/ — e.g. 'IntentClassifier.classify'."""

    for frame_info in inspect.stack()[2:]:

        module = frame_info.frame.f_globals.get("__name__", "")

        if module.startswith("models.") or module == __name__:
            continue

        owner = frame_info.frame.f_locals.get("self")
        name = frame_info.function

        return f"{type(owner).__name__}.{name}" if owner is not None else f"{module}.{name}"

    return "unknown"


class RequestMetrics:

    def __init__(self, label: str):

        self.label = label
        self.started = time.perf_counter()
        self.llm_calls = []
        self.store_calls = {}
        self.timings = {}
        self.finished = None

    @contextmanager
    def active(self):

        token = _CURRENT.set(self)

        try:
            yield self
        finally:
            _CURRENT.reset(token)

    def summary(self) -> dict:

        total_in = sum(c["in"] or 0 for c in self.llm_calls)
        total_out = sum(c["out"] or 0 for c in self.llm_calls)

        return {
            "label": self.label,
            "llm_calls": len(self.llm_calls),
            "tokens_in": total_in,
            "tokens_out": total_out,
            "tokens_total": total_in + total_out,
            "llm_ms": round(sum(c["ms"] for c in self.llm_calls)),
            "total_ms": round((time.perf_counter() - self.started) * 1000),
            "calls": self.llm_calls,
            "store_calls": dict(self.store_calls),
            "timings_ms": dict(self.timings),
        }

    def finish(self) -> dict:

        if self.finished is None:

            self.finished = self.summary()
            RECENT.append(self.finished)
            print("PERF " + json.dumps(self.finished))

        return self.finished


def current() -> RequestMetrics | None:

    return _CURRENT.get()


def record_llm_call(
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    ms: float,
    kind: str = "text",
    purpose: str | None = None,
    ok: bool = True
):

    metrics = _CURRENT.get()

    if metrics is None:
        return

    metrics.llm_calls.append({
        "caller": _caller_label(),
        "purpose": purpose,
        "model": model,
        "kind": kind,
        "in": prompt_tokens,
        "out": completion_tokens,
        "ms": round(ms),
        "ok": ok,
    })


def record_store_call(name: str):

    metrics = _CURRENT.get()

    if metrics is None:
        return

    metrics.store_calls[name] = metrics.store_calls.get(name, 0) + 1


def record_timing(name: str, ms: float):

    metrics = _CURRENT.get()

    if metrics is None:
        return

    metrics.timings[name] = round(metrics.timings.get(name, 0) + ms)
