import arxiv


class PaperService:

    def search_papers(
        self,
        query: str,
        max_results: int = 5
    ):

        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )

        papers = []

        for paper in search.results():

            papers.append({
                "title": paper.title,
                "authors": [
                    author.name
                    for author in paper.authors
                ],
                "summary": paper.summary,
                "published": str(paper.published),
                "pdf_url": paper.pdf_url
            })

        return papers