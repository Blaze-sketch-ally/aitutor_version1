import arxiv


def search_arxiv(query: str, max_results: int = 3):
    """
    Fetch research papers from arXiv
    """

    try:
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )

        results = []

        for paper in search.results():
            results.append({
                "title": paper.title,
                "summary": paper.summary,
                "published": str(paper.published),
                "url": paper.pdf_url
            })

        return results

    except Exception:
        return []