"""
One-shot retry for transient Supabase connection failures.

supabase-py keeps a long-lived HTTP/2 connection per service. When the
server closes it (e.g. after idling: httpx.RemoteProtocolError
"ConnectionTerminated"), every request multiplexed on it fails at once
— the browser audit saw /history, /pdfs and /selected-pdfs all return
500 together. The pool drops a dead connection after the error, so a
single retry on a fresh connection is enough.

Policy — retry exactly ONCE, and only when repeating can't duplicate a
write:
  * connection could not be established (ConnectError/ConnectTimeout):
    the request never reached the server -> any method.
  * connection dropped / read failed mid-request: only requests that are
    safe to repeat —
      GET/HEAD/OPTIONS (reads), PUT/PATCH/DELETE (idempotent),
      POST upserts (Prefer: resolution=merge-duplicates),
      POST to read-only RPCs in SAFE_RPCS.
    A plain INSERT is never retried after it may have been sent.
Anything else, or a second failure, is raised to the caller (main.py
turns it into a safe 503).
"""

import httpx

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"}

SAFE_RPCS = {"match_document_chunks"}

NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

TRANSIENT_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.ConnectError,
    httpx.ConnectTimeout,
)


def is_safe_to_repeat(request: httpx.Request) -> bool:

    if request.method in SAFE_METHODS:
        return True

    if request.method == "POST":

        if "resolution=merge-duplicates" in request.headers.get("prefer", ""):
            return True

        path = request.url.path.rstrip("/")

        if "/rpc/" in path and path.rsplit("/", 1)[-1] in SAFE_RPCS:
            return True

    return False


class RetryOnceTransport(httpx.BaseTransport):

    def __init__(self, inner: httpx.BaseTransport, label: str = "supabase"):

        self.inner = inner
        self.label = label

    def handle_request(self, request: httpx.Request) -> httpx.Response:

        try:
            return self.inner.handle_request(request)

        except TRANSIENT_ERRORS as e:

            if not (isinstance(e, NOT_SENT_ERRORS) or is_safe_to_repeat(request)):
                raise

            print(
                f"{self.label}: transient connection error "
                f"({type(e).__name__}) on {request.method} "
                f"{request.url.path}; retrying once on a new connection"
            )

            # Request bodies here are in-memory bytes, so they can be
            # sent again as-is.
            return self.inner.handle_request(request)

    def close(self):

        self.inner.close()


def install(client) -> None:
    """Wraps the PostgREST and Storage HTTP sessions of a supabase
    Client. Idempotent (won't double-wrap)."""

    sessions = [
        ("postgrest", getattr(client.postgrest, "session", None)),
        ("storage", getattr(client.storage, "session", None)
         or getattr(client.storage, "_client", None)),
    ]

    for label, session in sessions:

        if session is None or isinstance(session._transport, RetryOnceTransport):
            continue

        session._transport = RetryOnceTransport(session._transport, label=label)
