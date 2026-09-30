import requests


def search_wikipedia(query: str):
    """
    Step 1: Search Wikipedia for best matching page
    Step 2: Fetch summary of that page
    """

    # STEP 1: SEARCH
    search_url = "https://en.wikipedia.org/w/api.php"

    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json"
    }

    try:
        res = requests.get(search_url, params=params, timeout=10)
        data = res.json()

        if not data.get("query", {}).get("search"):
            return None

        title = data["query"]["search"][0]["title"]

        # STEP 2: SUMMARY
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

        res2 = requests.get(summary_url, timeout=10)

        if res2.status_code != 200:
            return None

        page = res2.json()

        return {
            "title": page.get("title"),
            "summary": page.get("extract"),
            "url": page.get("content_urls", {}).get("desktop", {}).get("page")
        }

    except Exception:
        return None