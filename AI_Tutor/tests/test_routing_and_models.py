import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import models.groq_client as groq_client
import models.router as router_module
from agents.intent_classifier import IntentClassifier
from models.errors import LLMQuotaExhaustedError, LLMServiceError


# =====================================================
# PHASE 10 — deterministic routing
# =====================================================

class TestDeterministicRouting:

    @pytest.mark.parametrize("query, flag", [
        ("hi, how are you?", "chat"),
        ("thanks!", "chat"),
        ("Generate notes from the PDF", "notes"),
        ("make notes on photosynthesis", "notes"),
        ("Generate a quiz from the PDF", "quiz"),
        ("quiz me on TCP", "quiz"),
        ("Compare TCP Tahoe and TCP Reno based on the PDF", "comparison"),
        ("what are the differences between CNN and RNN", "comparison"),
        ("Create a flowchart of TCP connection establishment", "diagram"),
        ("Create a bar chart using these values: A=10, B=20", "diagram"),
        ("plot y = x^2", "diagram"),
        ("give me youtube videos on recursion", "videos"),
        ("What is the reference course code for this chapter?", "answer"),
        ("How does TCP detect packet loss?", "answer"),
        ("why?", "answer"),
        ("summarize the uploaded pdf", "answer"),
        ("where can I apply for a passport", "external_action"),
        ("what's the latest news on AI regulation", "web_research"),
    ])
    @patch("agents.intent_classifier.route")
    def test_clear_requests_skip_the_llm(self, mock_route, query, flag):

        result = IntentClassifier().classify(query)

        mock_route.assert_not_called()
        assert result[flag] is True

    @pytest.mark.parametrize("query", [
        "explain photosynthesis and give a diagram",   # two families
        "notes and a quiz on TCP",                     # two families
        "photosynthesis",                              # no signal
        "I want to learn about neural networks",       # no clear form
        "teach me recursion with an example and a flowchart",
        "explain what AWS certification is and tell me where to register",
    ])
    @patch("agents.intent_classifier.route")
    def test_ambiguous_requests_use_the_llm(self, mock_route, query):

        mock_route.return_value = '{"answer": true}'

        clf = IntentClassifier()
        clf.classify(query)

        mock_route.assert_called_once()
        assert clf.last_route == "llm"
        assert mock_route.call_args.kwargs["purpose"] == "classify"

    @patch("agents.intent_classifier.route")
    def test_greeting_with_how_is_chat_not_answer(self, mock_route):

        # Baseline bug: the "how" follow-up shortcut sent this to the
        # tutor instead of chat.
        result = IntentClassifier().classify("hi, how are you?")

        assert result["chat"] is True
        assert result["answer"] is False

    @patch("agents.intent_classifier.route")
    def test_explicit_pdf_reference_is_kept(self, mock_route):

        result = IntentClassifier().classify("Generate notes from the PDF")

        assert result["knowledge_source"] == "pdf"

    @patch("agents.intent_classifier.route")
    def test_all_pdfs_notes_still_routed(self, mock_route):

        result = IntentClassifier().classify("create combined notes from all pdfs")

        assert result["notes"] and result["all_pdfs"]
        mock_route.assert_not_called()

    @patch("agents.intent_classifier.route", return_value='Sure! {"quiz": true}')
    def test_llm_json_with_preamble_is_parsed(self, _):

        assert IntentClassifier().classify("photosynthesis")["quiz"] is True

    @patch("agents.intent_classifier.route")
    def test_classifier_prompt_is_compact(self, mock_route):

        mock_route.return_value = "{}"
        IntentClassifier().classify("photosynthesis")

        # Was ~13k characters (~3.2k tokens) per call.
        assert len(mock_route.call_args.kwargs["prompt"]) < 4500

    @patch("agents.intent_classifier.route")
    def test_quota_error_is_not_swallowed(self, mock_route):

        mock_route.side_effect = LLMQuotaExhaustedError("daily")

        with pytest.raises(LLMQuotaExhaustedError):
            IntentClassifier().classify("photosynthesis")


# =====================================================
# PHASE 13/14 — model roles and budgets
# =====================================================

class TestModelRoles:

    def _route(self, purpose, **env):

        with patch.dict(os.environ, env), \
             patch.object(router_module, "groq_generate", return_value="ok") as gen:
            router_module.route(prompt="p", purpose=purpose)

        return gen.call_args.kwargs

    def test_internal_steps_use_fast_model_with_low_effort(self):

        kwargs = self._route("classify", FAST_MODEL="openai/gpt-oss-20b")

        assert kwargs["model"] == "openai/gpt-oss-20b"
        assert kwargs["reasoning_effort"] == "low"
        assert kwargs["max_tokens"] <= 1024

    def test_student_facing_output_uses_text_model(self):

        kwargs = self._route("answer", TEXT_MODEL="openai/gpt-oss-120b")

        assert kwargs["model"] == "openai/gpt-oss-120b"
        assert "reasoning_effort" not in kwargs

    def test_non_gpt_oss_model_gets_no_reasoning_effort(self):

        kwargs = self._route("classify", FAST_MODEL="qwen/qwen3.8-27b")

        assert "reasoning_effort" not in kwargs

    def test_no_purpose_keeps_legacy_call(self):

        with patch.object(router_module, "groq_generate", return_value="ok") as gen:
            router_module.route(prompt="p")

        assert set(gen.call_args.kwargs) == {"prompt", "model"}

    @pytest.mark.parametrize("module, purpose", [
        ("agents.query_resolver", "resolve"),
        ("memory.conversation_summary", "summarize"),
        ("agents.topic_extractor", "extract"),
    ])
    def test_internal_agents_declare_their_purpose(self, module, purpose):

        import importlib, inspect

        source = inspect.getsource(importlib.import_module(module))

        assert f'purpose="{purpose}"' in source


# =====================================================
# PHASE 15 — rate limits
# =====================================================

def _status_error(status, message, headers=None):

    e = Exception(message)
    e.status_code = status
    e.response = SimpleNamespace(headers=headers or {})
    return e


def _ok_response(text="ok"):

    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")]
    )


@pytest.fixture(autouse=False)
def fake_groq():

    groq_client._quota_blocked_until.clear()
    create = MagicMock()

    with patch.object(groq_client.client.chat.completions, "create", create), \
         patch.object(groq_client.time, "sleep") as sleep:
        yield create, sleep

    groq_client._quota_blocked_until.clear()


class TestRateLimitPolicy:

    TPM = "Rate limit reached for model `m` on tokens per minute (TPM): Limit 8000. Please try again in 2.5s."
    TPD = "Rate limit reached for model `m` on tokens per day (TPD): Limit 200000. Please try again in 20m4.4s."

    def test_per_minute_limit_waits_and_retries(self, fake_groq):

        create, sleep = fake_groq
        create.side_effect = [_status_error(429, self.TPM), _ok_response("done")]

        assert groq_client.generate("p", model="m") == "done"
        assert create.call_count == 2
        assert 2.5 <= sleep.call_args.args[0] <= 3.2

    def test_per_minute_retries_are_bounded(self, fake_groq):

        create, _ = fake_groq
        create.side_effect = _status_error(429, self.TPM)

        with pytest.raises(LLMServiceError):
            groq_client.generate("p", model="m")

        assert create.call_count == 1 + groq_client.MAX_RATE_LIMIT_RETRIES

    def test_long_wait_fails_fast(self, fake_groq):

        create, sleep = fake_groq
        create.side_effect = _status_error(
            429, "on tokens per minute (TPM). Please try again in 45s."
        )

        with pytest.raises(LLMServiceError):
            groq_client.generate("p", model="m")

        assert create.call_count == 1
        sleep.assert_not_called()

    def test_daily_quota_is_never_retried_and_blocks_follow_up_calls(self, fake_groq):

        create, sleep = fake_groq
        create.side_effect = _status_error(429, self.TPD)

        with pytest.raises(LLMQuotaExhaustedError) as err:
            groq_client.generate("p", model="m")

        assert create.call_count == 1
        sleep.assert_not_called()
        assert "daily usage limit" in err.value.user_message

        # The rest of the turn fails instantly — no second provider call.
        with pytest.raises(LLMQuotaExhaustedError):
            groq_client.generate("p2", model="m")

        assert create.call_count == 1

    def test_quota_block_is_per_model(self, fake_groq):

        create, _ = fake_groq
        create.side_effect = [_status_error(429, self.TPD), _ok_response("fast ok")]

        with pytest.raises(LLMQuotaExhaustedError):
            groq_client.generate("p", model="big")

        assert groq_client.generate("p", model="small") == "fast ok"

    def test_bad_request_is_not_retried(self, fake_groq):

        create, _ = fake_groq
        create.side_effect = _status_error(400, "bad request")

        with pytest.raises(LLMServiceError):
            groq_client.generate("p", model="m")

        assert create.call_count == 1

    def test_server_error_retried_once(self, fake_groq):

        create, _ = fake_groq
        create.side_effect = [_status_error(503, "unavailable"), _ok_response("ok")]

        assert groq_client.generate("p", model="m") == "ok"
        assert create.call_count == 2

    def test_retry_after_header_is_respected(self, fake_groq):

        create, sleep = fake_groq
        create.side_effect = [
            _status_error(429, "slow down", headers={"retry-after": "4"}),
            _ok_response("ok"),
        ]

        groq_client.generate("p", model="m")

        assert 4.0 <= sleep.call_args.args[0] <= 4.7

    def test_sdk_retries_are_disabled(self):

        assert groq_client.client.max_retries == 0
