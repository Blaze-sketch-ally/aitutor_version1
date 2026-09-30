import os
import pathlib
import re
from unittest.mock import patch

import pytest

from agents.video_summary_agent import VideoSummaryAgent
from models.config import get_groq_api_key

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _env(**values):

    clean = {
        k: v for k, v in os.environ.items()
        if k not in ("GROQ_APIKEY", "GROQ_API_KEY")
    }
    clean.update(values)

    return patch.dict(os.environ, clean, clear=True)


class TestGroqKeyAccessor:

    def test_canonical_name_wins(self):

        with _env(GROQ_APIKEY="canonical", GROQ_API_KEY="legacy"):
            assert get_groq_api_key() == "canonical"

    def test_deprecated_name_is_fallback(self):

        with _env(GROQ_API_KEY="legacy"):
            assert get_groq_api_key() == "legacy"

    def test_missing_key_is_none(self):

        with _env():
            assert get_groq_api_key() is None


class TestWhisperClientUsesCanonicalKey:

    def _agent(self):
        # Skip __init__ (it builds unrelated clients); only the key
        # lookup is under test.
        return object.__new__(VideoSummaryAgent)

    def test_whisper_client_reads_canonical_key(self):

        with _env(GROQ_APIKEY="canonical-test-key"), \
             patch("groq.Groq") as mock_groq:
            self._agent()._get_groq_client()

        mock_groq.assert_called_once_with(api_key="canonical-test-key")

    def test_whisper_client_error_names_canonical_var(self):

        with _env():
            with pytest.raises(RuntimeError, match="GROQ_APIKEY"):
                self._agent()._get_groq_client()


def test_no_backend_module_reads_groq_key_env_directly():
    """Only models/config.py may read the Groq key env vars."""

    offenders = []

    for path in BACKEND_ROOT.rglob("*.py"):

        rel = path.relative_to(BACKEND_ROOT).as_posix()

        if rel.startswith(("venv/", "tests/")) or rel == "models/config.py":
            continue

        text = path.read_text(encoding="utf-8", errors="ignore")

        if re.search(r"""getenv\(\s*["']GROQ_API_?KEY|environ(\.get)?[\[(]\s*["']GROQ_API_?KEY""", text):
            offenders.append(rel)

    assert offenders == []


class TestProviderErrorMessages:

    def _err(self, status, text):
        e = RuntimeError(text)
        e.status_code = status
        return e

    def test_daily_quota_is_not_reported_as_wait_a_moment(self):

        from models.errors import describe_provider_error

        msg = describe_provider_error(self._err(
            429, "Rate limit reached ... on tokens per day (TPD): Limit 200000"
        ))

        assert "daily usage limit" in msg
        assert "200000" not in msg

    def test_per_minute_limit_keeps_retry_message(self):

        from models.errors import describe_provider_error

        msg = describe_provider_error(self._err(
            429, "Rate limit reached ... on tokens per minute (TPM)"
        ))

        assert "wait a moment" in msg
