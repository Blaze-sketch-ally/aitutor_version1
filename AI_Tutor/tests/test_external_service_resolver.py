from unittest.mock import MagicMock

import pytest

from services.external_service_resolver import (
    ExternalServiceResolver,
    verify_url
)


class TestCheckRegistry:

    def test_registry_hit_does_not_call_tavily(self):

        resolver = ExternalServiceResolver()
        resolver.tavily = MagicMock()

        result = resolver.check_registry(
            "aws certification", "aws certification"
        )

        assert result is not None
        assert result["source_type"] == "official"
        resolver.tavily.search.assert_not_called()

    def test_no_registry_match_returns_none(self):

        resolver = ExternalServiceResolver()

        result = resolver.check_registry(
            "completely obscure unresolvable thing", "obscure thing"
        )

        assert result is None


class TestVerifyUrl:

    def test_rejects_non_https(self):

        assert verify_url("http://example.com", "example") is None

    def test_rejects_ip_literal(self):

        assert verify_url("https://192.168.1.1/apply", "passport") is None

    def test_rejects_known_shortener(self):

        assert verify_url("https://bit.ly/abc123", "passport") is None

    def test_rejects_no_topic_match(self):

        assert verify_url(
            "https://totally-unrelated-site.com", "passport application"
        ) is None

    def test_accepts_strong_domain_match_as_official(self):

        result = verify_url(
            "https://aws.amazon.com/certification/", "aws certification"
        )

        assert result == "official"

    def test_rejects_empty_url(self):

        assert verify_url("", "passport") is None


class TestSearchAndVerify:

    def test_no_search_results_returns_none(self):

        resolver = ExternalServiceResolver()
        resolver.tavily = MagicMock()
        resolver.tavily.search.return_value = []

        result = resolver.search_and_verify("some obscure service")

        assert result is None

    def test_unverifiable_candidates_return_none(self):

        resolver = ExternalServiceResolver()
        resolver.tavily = MagicMock()
        resolver.tavily.search.return_value = [
            {"title": "Unrelated Blog", "url": "https://random-blog.example", "domain": "random-blog.example"}
        ]

        result = resolver.search_and_verify("passport application")

        assert result is None

    def test_tavily_failure_is_not_swallowed_here(self):
        """
        search_and_verify() itself does not catch exceptions — matching
        every other services/*.py wrapper in this codebase (the calling
        agent is responsible for fail-soft behavior, not the service).
        """

        resolver = ExternalServiceResolver()
        resolver.tavily = MagicMock()
        resolver.tavily.search.side_effect = RuntimeError("tavily down")

        with pytest.raises(RuntimeError):
            resolver.search_and_verify("some service")
