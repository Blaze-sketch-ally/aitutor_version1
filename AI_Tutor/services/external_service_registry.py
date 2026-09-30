"""
Curated registry of known, high-value official services.

This is deliberately small and hand-picked — NOT an attempt to cover
"hundreds of services." It exists so a handful of common, unambiguous,
single-domain destinations (a certification provider, a company's own
careers page, a well-known developer/documentation site) can be answered
instantly and with full confidence, without spending a Tavily call or an
LLM call on something that's already known.

Deliberately NOT included: passports, visas, tax filing, and other
government/banking services that are jurisdiction-specific (there is no
single "the official passport site" — it depends on the user's country).
Those fall through to ExternalServiceResolver's Tavily-fallback path
instead of being guessed at here, since a wrong hardcoded entry would be
worse than no entry.

Adding a new service later is a one-entry addition to SERVICES below —
no new class, no new file.
"""

SERVICES = [
    # ---------------- Certifications ----------------
    {
        "service_name": "AWS Certification",
        "category": "certifications",
        "official_domain": "aws.amazon.com",
        "url": "https://aws.amazon.com/certification/",
        "description": "Official AWS certification registration and exam information.",
        "match_keywords": [
            "aws certification", "aws certified", "amazon web services certification",
            "aws exam"
        ]
    },
    {
        "service_name": "Google Cloud Certification",
        "category": "certifications",
        "official_domain": "cloud.google.com",
        "url": "https://cloud.google.com/certification",
        "description": "Official Google Cloud certification registration and exam information.",
        "match_keywords": [
            "google cloud certification", "gcp certification", "google cloud certified"
        ]
    },
    {
        "service_name": "Microsoft Certifications",
        "category": "certifications",
        "official_domain": "learn.microsoft.com",
        "url": "https://learn.microsoft.com/en-us/credentials/",
        "description": "Official Microsoft (including Azure) certification registration.",
        "match_keywords": [
            "microsoft certification", "azure certification", "microsoft certified"
        ]
    },

    # ---------------- Jobs / careers ----------------
    {
        "service_name": "Google Careers",
        "category": "jobs",
        "official_domain": "careers.google.com",
        "url": "https://careers.google.com/",
        "description": "Official Google careers and job application portal.",
        "match_keywords": ["google careers", "google jobs", "apply at google", "work at google"]
    },
    {
        "service_name": "Microsoft Careers",
        "category": "jobs",
        "official_domain": "careers.microsoft.com",
        "url": "https://careers.microsoft.com/",
        "description": "Official Microsoft careers and job application portal.",
        "match_keywords": ["microsoft careers", "microsoft jobs", "apply at microsoft", "work at microsoft"]
    },
    {
        "service_name": "LinkedIn Jobs",
        "category": "jobs",
        "official_domain": "linkedin.com",
        "url": "https://www.linkedin.com/jobs/",
        "description": "General job search and applications across many employers.",
        "match_keywords": ["linkedin jobs", "job search", "find a job", "job listings"]
    },
    {
        "service_name": "Indeed",
        "category": "jobs",
        "official_domain": "indeed.com",
        "url": "https://www.indeed.com/",
        "description": "General job search and applications across many employers.",
        "match_keywords": ["indeed jobs", "indeed.com"]
    },

    # ---------------- Online learning ----------------
    {
        "service_name": "Coursera",
        "category": "online_learning",
        "official_domain": "coursera.org",
        "url": "https://www.coursera.org/",
        "description": "Online courses and certificates from universities and companies.",
        "match_keywords": ["coursera"]
    },
    {
        "service_name": "edX",
        "category": "online_learning",
        "official_domain": "edx.org",
        "url": "https://www.edx.org/",
        "description": "Online courses from universities and institutions.",
        "match_keywords": ["edx"]
    },
    {
        "service_name": "Khan Academy",
        "category": "online_learning",
        "official_domain": "khanacademy.org",
        "url": "https://www.khanacademy.org/",
        "description": "Free online courses and practice exercises.",
        "match_keywords": ["khan academy"]
    },
    {
        "service_name": "Udemy",
        "category": "online_learning",
        "official_domain": "udemy.com",
        "url": "https://www.udemy.com/",
        "description": "Paid online courses on a wide range of topics.",
        "match_keywords": ["udemy"]
    },

    # ---------------- Developer / cloud services ----------------
    {
        "service_name": "GitHub",
        "category": "developer_services",
        "official_domain": "github.com",
        "url": "https://github.com/",
        "description": "Code hosting, version control, and developer collaboration.",
        "match_keywords": ["github", "create a repository", "host my code"]
    },
    {
        "service_name": "AWS Console",
        "category": "cloud_services",
        "official_domain": "aws.amazon.com",
        "url": "https://aws.amazon.com/console/",
        "description": "Amazon Web Services account and console access.",
        "match_keywords": ["aws console", "amazon web services account", "sign up for aws"]
    },

    # ---------------- Documentation ----------------
    {
        "service_name": "MDN Web Docs",
        "category": "documentation",
        "official_domain": "developer.mozilla.org",
        "url": "https://developer.mozilla.org/",
        "description": "Official reference documentation for web technologies (HTML, CSS, JS).",
        "match_keywords": ["mdn", "mdn web docs", "mozilla developer network"]
    },
    {
        "service_name": "Python Documentation",
        "category": "documentation",
        "official_domain": "docs.python.org",
        "url": "https://docs.python.org/3/",
        "description": "Official Python language and standard library documentation.",
        "match_keywords": ["python documentation", "python docs", "official python docs"]
    },
    {
        "service_name": "Stack Overflow",
        "category": "documentation",
        "official_domain": "stackoverflow.com",
        "url": "https://stackoverflow.com/",
        "description": "Community Q&A for programming questions.",
        "match_keywords": ["stack overflow", "stackoverflow"]
    },

    # ---------------- Travel ----------------
    {
        "service_name": "Skyscanner",
        "category": "travel",
        "official_domain": "skyscanner.net",
        "url": "https://www.skyscanner.net/",
        "description": "Flight, hotel, and car hire search and comparison.",
        "match_keywords": ["skyscanner", "flight search", "book a flight", "search flights", "compare flights"]
    },

    # ---------------- Shopping ----------------
    {
        "service_name": "Amazon",
        "category": "shopping",
        "official_domain": "amazon.com",
        "url": "https://www.amazon.com/",
        "description": "General online shopping and marketplace.",
        "match_keywords": ["amazon shopping", "buy on amazon", "order from amazon"]
    },

    # ---------------- Payments / banking ----------------
    {
        "service_name": "PayPal",
        "category": "banking",
        "official_domain": "paypal.com",
        "url": "https://www.paypal.com/",
        "description": "Online payments and money transfers.",
        "match_keywords": ["paypal"]
    },

    # ---------------- Healthcare ----------------
    {
        "service_name": "World Health Organization",
        "category": "healthcare",
        "official_domain": "who.int",
        "url": "https://www.who.int/",
        "description": "Official global public health information.",
        "match_keywords": ["world health organization", "who.int", "official health information"]
    },
]


def _score(query: str, entry: dict) -> int:

    q = query.lower()

    return sum(
        1
        for keyword in entry["match_keywords"]
        if keyword in q
    )


def lookup(query: str) -> dict | None:
    """
    Keyword-overlap match against the curated registry above. Returns
    the single best-matching entry, or None if nothing matches — callers
    (ExternalServiceResolver) fall back to Tavily search when this
    returns None, they don't guess.
    """

    if not query or not query.strip():
        return None

    best_entry = None
    best_score = 0

    for entry in SERVICES:

        score = _score(query, entry)

        if score > best_score:
            best_score = score
            best_entry = entry

    return best_entry
