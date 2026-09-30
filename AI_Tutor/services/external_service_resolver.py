import re
from urllib.parse import urlparse

from services import external_service_registry
from services.tavily_service import TavilyService


_URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "rebrand.ly", "cutt.ly", "shorte.st", "adf.ly"
}


def _significant_words(text: str) -> list[str]:

    words = re.findall(r"[a-z0-9]+", text.lower())

    return [w for w in words if len(w) > 2]


def _is_ip_literal(hostname: str) -> bool:

    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", hostname):
        return True

    # crude IPv6-literal check — real IPv6 hostnames contain colons,
    # which no normal DNS hostname ever does
    if ":" in hostname:
        return True

    return False


def _is_suspicious_hostname(hostname: str) -> bool:
    """
    Non-ASCII or punycode ("xn--") hostnames are a classic homograph-
    spoofing signal (e.g. a Cyrillic lookalike of "amazon.com"). This
    is a cheap, imperfect check — not a substitute for a real domain-
    reputation service — but it's a meaningful bar to clear.
    """

    try:
        hostname.encode("ascii")
    except UnicodeEncodeError:
        return True

    if "xn--" in hostname.lower():
        return True

    return False


def _match_strength(hostname: str, topic: str) -> str | None:
    """
    "official" when a topic word exactly matches one of the hostname's
    dot-separated labels (e.g. "aws" matching the "aws" in
    "aws.amazon.com" — a precise, structural match, not a coincidence),
    or when a long/distinctive word matches anywhere in the hostname.
    "unverified" for a shorter, merely-substring match. None when
    nothing matches at all (caller should reject).
    """

    host = hostname.lower()
    labels = host.split(".")

    best_match = None
    exact_label_hit = False

    for word in _significant_words(topic):

        if word in labels:

            exact_label_hit = True

            if best_match is None or len(word) > len(best_match):
                best_match = word

        elif word in host:

            if best_match is None or len(word) > len(best_match):
                best_match = word

    if best_match is None:
        return None

    if exact_label_hit:
        return "official"

    return "official" if len(best_match) >= 5 else "unverified"


def verify_url(url: str, topic: str) -> str | None:
    """
    Runs a candidate URL through the security checks described in the
    plan: HTTPS only, no IP-literal hosts, no known shorteners, no
    suspicious/punycode hostnames, and the hostname must lexically
    relate to the resolved topic. Returns a source_type ("official" /
    "unverified") on success, or None — meaning "do not show this URL
    at all", not "show it with a warning".
    """

    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    if parsed.scheme != "https":
        return None

    hostname = parsed.hostname or ""

    if not hostname:
        return None

    if _is_ip_literal(hostname):
        return None

    if hostname.lower() in _URL_SHORTENERS:
        return None

    if _is_suspicious_hostname(hostname):
        return None

    return _match_strength(hostname, topic)


class ExternalServiceResolver:
    """
    Two-tier resolution: the curated registry first (instant, zero
    network/LLM cost, always "official"), then a Tavily-backed fallback
    with URL verification for anything not in the registry. Returns
    None — never a guess — when nothing clears the verification bar.
    """

    def __init__(self):

        self.tavily = TavilyService()

    def check_registry(self, query: str, resolved_topic: str) -> dict | None:

        registry_hit = (
            external_service_registry.lookup(query)
            or external_service_registry.lookup(resolved_topic)
        )

        if not registry_hit:
            return None

        return {
            "label": f"Open {registry_hit['service_name']}",
            "url": registry_hit["url"],
            "service": registry_hit["service_name"],
            "source_type": "official"
        }

    def search_and_verify(self, resolved_topic: str) -> dict | None:

        candidates = self.tavily.search(
            f"{resolved_topic} official website",
            topic="general",
            max_results=5
        )

        for candidate in candidates:

            source_type = verify_url(
                candidate.get("url", ""),
                resolved_topic
            )

            if source_type:

                title = candidate.get("title") or candidate.get("domain", "Website")

                label = (
                    f"Open {title}"
                    if len(title) <= 40
                    else "Open Website"
                )

                return {
                    "label": label,
                    "url": candidate["url"],
                    "service": candidate.get("domain", title),
                    "source_type": source_type
                }

        return None

    def resolve(self, query: str, resolved_topic: str) -> dict | None:
        """
        Convenience entry point: registry first, Tavily fallback second.
        TaskRouterAgent calls check_registry()/search_and_verify()
        separately instead of this method, so each step gets its own
        LangSmith trace span — this method exists for simpler callers
        (and tests) that just want the end result.
        """

        return (
            self.check_registry(query, resolved_topic)
            or self.search_and_verify(resolved_topic)
        )
