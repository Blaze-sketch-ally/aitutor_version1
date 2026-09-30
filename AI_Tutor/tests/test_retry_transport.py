import httpx
import pytest
from fastapi.testclient import TestClient

from database.retry_transport import RetryOnceTransport, install, is_safe_to_repeat

BASE = "https://example.supabase.co"


class FlakyTransport(httpx.BaseTransport):
    """Fails the first `failures` requests with `error`, then answers 200."""

    def __init__(self, error, failures=1):
        self.error, self.failures, self.calls = error, failures, 0

    def handle_request(self, request):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error("connection terminated", request=request)
        return httpx.Response(200, json=[{"ok": True}], request=request)


def _client(inner):
    return httpx.Client(transport=RetryOnceTransport(inner), base_url=BASE)


class TestRetryPolicy:

    def test_dropped_connection_on_read_is_retried_once(self):

        inner = FlakyTransport(httpx.RemoteProtocolError)

        r = _client(inner).get("/rest/v1/messages?session_id=eq.x")

        assert r.status_code == 200
        assert inner.calls == 2

    def test_second_failure_is_raised_not_retried_again(self):

        inner = FlakyTransport(httpx.RemoteProtocolError, failures=5)

        with pytest.raises(httpx.RemoteProtocolError):
            _client(inner).get("/rest/v1/messages")

        assert inner.calls == 2

    def test_plain_insert_is_never_repeated_after_being_sent(self):

        inner = FlakyTransport(httpx.RemoteProtocolError)

        with pytest.raises(httpx.RemoteProtocolError):
            _client(inner).post("/rest/v1/messages", json=[{"content": "hi"}])

        assert inner.calls == 1  # no duplicate write

    def test_insert_retried_when_connection_never_established(self):

        inner = FlakyTransport(httpx.ConnectError)

        r = _client(inner).post("/rest/v1/messages", json=[{"content": "hi"}])

        assert r.status_code == 200
        assert inner.calls == 2

    @pytest.mark.parametrize("method, path, headers, safe", [
        ("GET", "/rest/v1/sessions", {}, True),
        ("DELETE", "/rest/v1/pdfs", {}, True),
        ("PATCH", "/rest/v1/sessions", {}, True),
        ("POST", "/rest/v1/document_chunks", {"Prefer": "resolution=merge-duplicates"}, True),
        ("POST", "/rest/v1/rpc/match_document_chunks", {}, True),
        ("POST", "/rest/v1/messages", {}, False),
        ("POST", "/rest/v1/rpc/some_writing_function", {}, False),
    ])
    def test_safe_to_repeat_classification(self, method, path, headers, safe):

        request = httpx.Request(method, BASE + path, headers=headers)

        assert is_safe_to_repeat(request) is safe


class TestInstall:

    def test_real_client_sessions_are_wrapped_once(self):

        from database.supabase_client import supabase

        install(supabase)  # second call must not double-wrap

        transport = supabase.postgrest.session._transport
        assert isinstance(transport, RetryOnceTransport)
        assert not isinstance(transport.inner, RetryOnceTransport)


class TestApiErrorMapping:

    def test_unrecovered_connection_error_is_safe_503(self):

        from unittest.mock import patch

        import api.session as session_api
        from auth.jwt_bearer import CurrentUser, get_current_user
        from main import app

        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u")

        with patch.object(
            session_api.session_service, "get_history",
            side_effect=httpx.RemoteProtocolError("<ConnectionTerminated error_code:9>")
        ):
            r = TestClient(app).get("/api/session/s/history")

        assert r.status_code == 503
        assert "Temporary connection problem" in r.json()["detail"]
        assert "ConnectionTerminated" not in r.text
