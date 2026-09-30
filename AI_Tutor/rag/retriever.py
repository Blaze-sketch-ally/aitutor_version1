import json
import re

import numpy as np

from models.errors import RetrievalError
from rag.vectorstore import VectorStore


# =====================================
# RELEVANCE FILTERING
# =====================================
# Metric: pgvector's <=> operator = cosine DISTANCE = 1 - cosine
# similarity, on L2-normalized all-MiniLM-L6-v2 embeddings (384-d).
# 0 = identical direction; unrelated text sits around 0.85-1.0.
#
# Calibrated 2026-09-29 against a 7-chunk TCP chapter, 10 answerable
# and 10 unrelated questions (short question vs ~1000-char chunk):
#   answerable, best chunk:  0.23 - 0.71   (plus 0.92 for a question
#                            whose answer is only a lexical match)
#   unrelated,  best chunk:  0.79 - 0.96   (0.71 for an adjacent
#                            networking topic, HTTP caching)
# The old cutoff of 0.55 (cos-sim >= 0.45, a straight port of the
# ChromaDB threshold) discarded 4/10 answerable questions.
#
# Distance alone cannot separate the two groups perfectly, so
# get_relevant_chunks() combines:
#   1. dense top-k candidates per PDF, ranked by distance;
#   2. an absolute ceiling (MAX_RELEVANT_DISTANCE) — nothing weaker is
#      ever treated as evidence;
#   3. a relative band — chunks much weaker than the best hit are
#      dropped, so one good match doesn't drag in the tail;
#   4. lexical evidence — a chunk that literally contains an
#      identifier from the query (e.g. ALPHA_UNIQUE_48291), or most of
#      the query's content words, counts as evidence even when its
#      dense distance is weak.
# If nothing qualifies, NO context is returned — callers must treat
# that as "the selected material doesn't cover this", never pad it
# with arbitrary chunks.
#
# Re-derive these if the embedding model or chunk size changes.

MAX_RELEVANT_DISTANCE = 0.78

RELATIVE_DISTANCE_BAND = 0.20

CANDIDATES_PER_PDF = 8

MIN_LEXICAL_OVERLAP = 0.6

# Kept for callers/signatures that pass `threshold` explicitly; it is
# the absolute ceiling above.
DEFAULT_RELEVANCE_THRESHOLD = MAX_RELEVANT_DISTANCE

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "from", "by", "with", "about", "as", "into", "over", "is",
    "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "what", "which", "who", "whom", "whose", "when", "where", "why",
    "how", "this", "that", "these", "those", "it", "its", "i", "me",
    "my", "you", "your", "we", "our", "they", "their", "he", "she",
    "can", "could", "would", "should", "will", "shall", "may", "might",
    "must", "please", "tell", "explain", "describe", "give", "show",
    "list", "define", "according", "pdf", "pdfs", "document", "file",
    "uploaded", "selected", "notes", "material", "some", "any", "all",
    "there", "here", "than", "then", "also", "not", "no", "yes", "if",
    "so", "such", "very", "much", "many", "more", "most", "work",
    "works", "use", "used", "using", "mean", "means", "example",
    "examples"
}

# Phrases that only say WHERE to look — they add noise to the query
# embedding without saying anything about the content.
_SOURCE_PHRASE_RE = re.compile(
    r"\b(according to|based on|from|in|using|as per|per)\s+"
    r"(the|this|my|our|uploaded|attached|selected)?\s*"
    r"(uploaded\s+|attached\s+|selected\s+)?"
    r"(pdfs?|documents?|docs?|files?|material|materials)\b[,:]?",
    re.IGNORECASE
)


def _clean_query(query: str) -> str:

    cleaned = _SOURCE_PHRASE_RE.sub(" ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.:;")

    return cleaned or query


def _content_terms(text: str) -> set[str]:

    return {
        token
        for token in re.findall(r"[a-z0-9_]+", text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _identifier_terms(query: str) -> list[str]:
    """
    Tokens that look like identifiers/codes (contain a digit or an
    underscore, e.g. ALPHA_UNIQUE_48291, RFC5681, x_max) — worth an
    exact-substring lookup since embeddings represent them poorly.
    """

    return [
        token
        for token in re.findall(r"[A-Za-z0-9_\-]{4,}", query)
        if re.search(r"[0-9_]", token) and re.search(r"[A-Za-z]", token)
    ]


# Words that describe the requested OUTPUT or the document itself
# rather than a subject ("generate notes from the pdf", "summarize
# this file", "quiz me on the whole document").
_REQUEST_WORDS = {
    "generate", "create", "make", "write", "prepare", "produce", "want",
    "need", "summarize", "summarise", "summary", "summaries", "overview",
    "quiz", "quizzes", "question", "questions", "mcq", "mcqs", "test",
    "note", "video", "videos", "youtube", "paper", "papers", "research",
    "diagram", "flowchart", "chart", "graph", "main", "key", "points",
    "ideas", "topics", "topic", "important", "short", "long", "detailed",
    "brief", "based", "content", "contents", "whole", "entire",
    "everything", "covered", "cover", "covers", "docs", "files",
    "documents", "materials", "attached", "compare", "comparison", "two",
    "both", "between", "difference", "differences", "similarities",
    "related", "relevant", "things", "stuff", "points", "revision",
    "study", "learn", "help", "quick", "simple", "simply", "easy"
}


def query_topic_terms(query: str) -> set[str]:
    """
    Subject words left in a query once PDF references and output/
    request words are removed. Empty => the request is about the
    document as a whole ("summarize the pdf", "make notes from my
    document"), not a specific topic inside it.
    """

    return _content_terms(_clean_query(query)) - _REQUEST_WORDS


def _lexical_overlap(query_terms: set[str], text: str) -> float:

    if not query_terms:
        return 0.0

    return len(query_terms & _content_terms(text)) / len(query_terms)


def _parse_embedding(value):

    if isinstance(value, str):
        value = json.loads(value)

    return np.asarray(value, dtype=float)


class Retriever:

    def __init__(
        self,
        session_id: str,
        top_k: int = 5
    ):

        self.vectorstore = VectorStore(
            session_id=session_id
        )

        self.top_k = top_k

    # ----------------------------------
    # RELEVANT CHUNKS (candidates -> rank -> filter)
    # ----------------------------------
    # See the RELEVANCE FILTERING notes at the top of this module.
    # Returns [{"document", "distance", "metadata", "lexical"}] sorted
    # best-first, containing ONLY chunks that qualify as evidence —
    # possibly empty.

    def get_relevant_chunks(
        self,
        query: str,
        selected_pdfs: list[str] | None = None,
        top_k: int | None = None,
        threshold: float = MAX_RELEVANT_DISTANCE,
        per_pdf_limit: int | None = None
    ) -> list[dict]:

        top_k = top_k or self.top_k
        search_query = _clean_query(query)
        query_terms = _content_terms(search_query)
        identifiers = _identifier_terms(search_query)

        pdf_names = selected_pdfs or [None]

        candidates = {}

        for pdf_name in pdf_names:

            results = self.vectorstore.search(
                query=search_query,
                pdf_name=pdf_name,
                n_results=max(CANDIDATES_PER_PDF, top_k)
            )

            for chunk_id, doc, dist, meta in zip(
                results.get("ids", []),
                results.get("documents", []),
                results.get("distances", []),
                results.get("metadatas", [])
            ):

                candidates[chunk_id] = {
                    "document": doc,
                    "distance": dist,
                    "metadata": meta or {}
                }

            # Exact identifier matches the dense search may have missed.
            if identifiers:

                query_vector = None

                for term in identifiers:

                    hits = self.vectorstore.keyword_search(
                        term,
                        pdf_name=pdf_name,
                        limit=3
                    )

                    for chunk_id, doc, meta, emb in zip(
                        hits["ids"],
                        hits["documents"],
                        hits["metadatas"],
                        hits["embeddings"]
                    ):

                        if chunk_id in candidates:
                            continue

                        if query_vector is None:
                            query_vector = np.asarray(
                                self.vectorstore.embedder.embed_query(
                                    search_query
                                )
                            )

                        try:
                            dist = float(
                                1 - _parse_embedding(emb) @ query_vector
                            )
                        except Exception:
                            dist = 1.0

                        candidates[chunk_id] = {
                            "document": doc,
                            "distance": dist,
                            "metadata": meta or {}
                        }

        if not candidates:
            return []

        best_distance = min(c["distance"] for c in candidates.values())

        # Grouped (per-PDF) retrieval judges each PDF against its own
        # best hit, so a weaker-but-relevant PDF isn't cut from a
        # comparison just because another PDF matched more strongly.
        best_by_source = {}

        for c in candidates.values():

            key = c["metadata"].get("source") if per_pdf_limit else None
            best_by_source[key] = min(
                best_by_source.get(key, c["distance"]),
                c["distance"]
            )

        relevant = []

        for item in candidates.values():

            key = item["metadata"].get("source") if per_pdf_limit else None
            band_limit = min(
                threshold,
                best_by_source[key] + RELATIVE_DISTANCE_BAND
            )

            text = item["document"] or ""

            lexical = _lexical_overlap(query_terms, text)

            has_identifier = any(
                term.lower() in text.lower() for term in identifiers
            )

            lexical_evidence = has_identifier or (
                lexical >= MIN_LEXICAL_OVERLAP
                and len(query_terms) >= 2
            )

            if item["distance"] <= band_limit or lexical_evidence:

                relevant.append({**item, "lexical": lexical})

        # Rank: dense distance, nudged by lexical overlap so a chunk that
        # literally contains the asked-about terms outranks a vaguely
        # similar one.
        relevant.sort(key=lambda x: x["distance"] - 0.3 * x["lexical"])

        if per_pdf_limit:

            counts = {}
            limited = []

            for item in relevant:

                source = item["metadata"].get("source")
                counts[source] = counts.get(source, 0) + 1

                if counts[source] <= per_pdf_limit:
                    limited.append(item)

            relevant = limited

        else:

            relevant = relevant[:top_k]

        print(
            f"Retriever: {len(candidates)} candidates, "
            f"{len(relevant)} relevant (best distance "
            f"{best_distance:.3f}, ceiling {threshold})"
        )

        return relevant

    # ----------------------------------
    # RETRIEVE DOCUMENTS
    # ----------------------------------

    def retrieve(
    self,
    query: str,
    selected_pdfs: list[str] | None = None,
    top_k: int | None = None
):

        try:

            # --------------------------
            # NORMAL RETRIEVAL
            # --------------------------

            if not selected_pdfs:

                results = self.vectorstore.search(
                    query=query,
                    n_results=top_k or self.top_k
                )

                return results.get(
                    "documents",
                    []
                )

            # --------------------------
            # BALANCED RETRIEVAL
            # --------------------------

            total_k = top_k or self.top_k

            per_pdf_k = max(
                1,
                total_k // len(selected_pdfs)
            )

            all_documents = []

            for pdf_name in selected_pdfs:

                results = self.vectorstore.search(
                    query=query,
                    pdf_name=pdf_name,
                    n_results=per_pdf_k
                )

                docs = results.get(
                    "documents",
                    []
                )

                all_documents.extend(docs)

            return all_documents

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return []

    # ----------------------------------
    # RETRIEVE WITH SCORES
    # ----------------------------------

    def retrieve_with_scores(
    self,
    query: str,
    selected_pdfs: list[str] | None = None,
    top_k: int | None = None
):

        try:

            if not selected_pdfs:

                results = self.vectorstore.search(
                    query=query,
                    n_results=top_k or self.top_k
                )

                documents = results.get(
                    "documents",
                    []
                )

                distances = results.get(
                    "distances",
                    []
                )

            else:

                documents = []
                distances = []

                total_k = top_k or self.top_k

                per_pdf_k = max(
                    1,
                    total_k // len(selected_pdfs)
                )

                for pdf_name in selected_pdfs:

                    pdf_results = self.vectorstore.search(
                        query=query,
                        pdf_name=pdf_name,
                        n_results=per_pdf_k
                    )

                    documents.extend(
                        pdf_results.get(
                            "documents",
                            []
                        )
                    )

                    distances.extend(
                        pdf_results.get(
                            "distances",
                            []
                        )
                    )

            scored_results = []

            for doc, dist in zip(
                documents,
                distances
            ):

                scored_results.append(
                    {
                        "document": doc,
                        "distance": dist
                    }
                )

            scored_results.sort(
                key=lambda x: x["distance"]
            )

            return scored_results

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return []
    # ----------------------------------
    # RETRIEVE WITH METADATA
    # ----------------------------------

    def retrieve_with_metadata(
    self,
    query: str,
    selected_pdfs: list[str] | None = None,
    top_k: int | None = None
):

        try:

            if not selected_pdfs:

                results = self.vectorstore.search(
                    query=query,
                    n_results=top_k or self.top_k
                )

                documents = results.get(
                    "documents",
                    []
                )

                distances = results.get(
                    "distances",
                    []
                )

                metadatas = results.get(
                    "metadatas",
                    []
                )

            else:

                documents = []
                distances = []
                metadatas = []

                total_k = top_k or self.top_k

                per_pdf_k = max(
                    1,
                    total_k // len(selected_pdfs)
                )

                for pdf_name in selected_pdfs:

                    pdf_results = self.vectorstore.search(
                        query=query,
                        pdf_name=pdf_name,
                        n_results=per_pdf_k
                    )

                    documents.extend(
                        pdf_results.get(
                            "documents",
                            []
                        )
                    )

                    distances.extend(
                        pdf_results.get(
                            "distances",
                            []
                        )
                    )

                    metadatas.extend(
                        pdf_results.get(
                            "metadatas",
                            []
                        )
                    )

            output = []

            for doc, dist, meta in zip(
                documents,
                distances,
                metadatas
            ):

                output.append(
                    {
                        "document": doc,
                        "distance": dist,
                        "metadata": meta or {}
                    }
                )

            output.sort(
                key=lambda x: x["distance"]
            )

            return output

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return []

    # ----------------------------------
    # GET CONTEXT ONLY
    # ----------------------------------

    def get_context(
        self,
        query: str,
        threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
        selected_pdfs:list[str]|None=None,
        top_k:int|None=None
        
    ) -> str:

        try:

            results = self.retrieve_with_scores(
                query=query,
                selected_pdfs= selected_pdfs,
                top_k=top_k
                
            )

            if not results:

                print(
                    "No retrieval results."
                )

                return ""

            relevant_chunks = []

            for item in results:

                distance = item.get(
                    "distance",
                    999
                )

                print(
                    f"Distance: {distance}"
                )

                if distance <= threshold:

                    relevant_chunks.append(
                        item["document"]
                    )

            if not relevant_chunks:

                print(
                    "No relevant PDF context found."
                )

                return ""

            print(
                f"Retrieved {len(relevant_chunks)} relevant chunks."
            )

            return "\n\n".join(
                relevant_chunks
            )

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return ""

    # ----------------------------------
    # GET CONTEXT + SOURCES
    # ----------------------------------

    def get_context_with_sources(
        self,
        query: str,
        threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
        top_k:int|None=None,
        selected_pdfs:list[str]|None=None
    ):

        try:

            # Already ranked and relevance-filtered — see
            # get_relevant_chunks(). The distance check in the loop
            # below is kept as a harmless guard; lexically-qualified
            # chunks may legitimately exceed it, so it uses +inf here.
            results = self.get_relevant_chunks(
                query=query,
                selected_pdfs=selected_pdfs,
                top_k=top_k,
                threshold=threshold
            )
            threshold = float("inf")

            if not results:

                return {
                    "context": "",
                    "sources": []
                }

            context_chunks = []
            sources = []
            seen_sources = set()

            for item in results:

                distance = item.get(
                    "distance",
                    999
                )

                if distance > threshold:

                    continue

                context_chunks.append(
                    item["document"]
                )

                metadata = item.get(
                    "metadata",
                    {}
                )

                source_name = metadata.get(
                    "source",
                    "Unknown"
                )

                page = metadata.get(
                    "page",
                    "N/A"
                )

                chunk_id = metadata.get(
                    "chunk_id",
                    "N/A"
                )

                key = (
                    source_name,
                    page,
                    chunk_id
                )

                if key not in seen_sources:

                    seen_sources.add(
                        key
                    )

                    sources.append(
                        {
                            "source": source_name,
                            "page": page,
                            "chunk_id": chunk_id,
                            "distance": round(
                                distance,
                                4
                            )
                        }
                    )

            sources = sorted(
                sources,
                key=lambda x: x["distance"]
            )

            return {

                "context": "\n\n".join(
                    context_chunks
                ),

                "sources": sources
            }

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return {
                "context": "",
                "sources": []
            }
    # ----------------------------------
    # GROUP CONTEXT BY PDF
    # ----------------------------------

    def get_grouped_context_by_source(
        self,
        query: str,
        threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
        top_k: int|None=None,
        selected_pdfs:list[str]|None=None
    ):

        try:

            # Per-PDF relevance filtering (see get_relevant_chunks);
            # a PDF with no qualifying chunk is simply absent from
            # pdf_contexts rather than padded with unrelated text.
            results = self.get_relevant_chunks(
                query=query,
                selected_pdfs=selected_pdfs,
                top_k=top_k,
                threshold=threshold,
                per_pdf_limit=top_k or self.top_k
            )
            threshold = float("inf")

            if not results:

                return {
                    "pdf_contexts": {},
                    "sources": []
                }

            pdf_contexts = {}

            sources = []

            for item in results:

                distance = item.get(
                    "distance",
                    999
                )

                if distance > threshold:

                    continue

                metadata = item.get(
                    "metadata",
                    {}
                )

                source_name = metadata.get(
                    "source",
                    "Unknown PDF"
                )

                page = metadata.get(
                    "page",
                    "N/A"
                )

                chunk_id = metadata.get(
                    "chunk_id",
                    "N/A"
                )

                document = item.get(
                    "document",
                    ""
                )

                if source_name not in pdf_contexts:

                    pdf_contexts[source_name] = []

                pdf_contexts[source_name].append(
                    document
                )

                sources.append(
                    {
                        "source": source_name,
                        "page": page,
                        "chunk_id": chunk_id,
                        "distance": round(
                            distance,
                            4
                        )
                    }
                )

            final_contexts = {}

            for pdf_name, chunks in (
                pdf_contexts.items()
            ):

                final_contexts[pdf_name] = (
                    "\n\n".join(chunks)
                )

            return {

                "pdf_contexts": final_contexts,

                "sources": sorted(
                    sources,
                    key=lambda x: x["distance"]
                )
            }

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return {
                "pdf_contexts": {},
                "sources": []
            }

    # ----------------------------------
    # PDF RELEVANCE CHECK
    # ----------------------------------

    def is_pdf_relevant(
        self,
        query: str,
        threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
        selected_pdfs:list[str]|None=None
    ) -> bool:

        try:

            return bool(
                self.get_relevant_chunks(
                    query=query,
                    selected_pdfs=selected_pdfs,
                    threshold=threshold
                )
            )

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return False

    # ----------------------------------
    # BEST DISTANCE
    # ----------------------------------

    def best_distance(
        self,
        query: str
    ):

        try:

            results = self.retrieve_with_scores(
                query
            )

            if not results:

                return None

            best = min(
                item["distance"]
                for item in results
            )

            print(
                f"Best Distance: {best}"
            )

            return best

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return None

    # ----------------------------------
    # REPRESENTATIVE CONTEXT (no similarity search)
    # ----------------------------------
    # Returns {pdf_name: joined_text} using a straight metadata-
    # filtered sample of each PDF's own chunks. Use this instead of
    # get_context_with_sources() / get_grouped_context_by_source()
    # when the caller needs "what is this PDF actually about" rather
    # than "what matches this specific query" — e.g. video/topic
    # suggestions requested via a meta-instruction like "give me
    # videos on the pdf I uploaded", where the literal query text has
    # no real semantic content to search against.

    def get_representative_context(
        self,
        selected_pdfs: list[str] | None,
        max_chunks_per_pdf: int = 6
    ) -> dict:

        try:

            if not selected_pdfs:

                return {}

            contexts = {}

            for pdf_name in selected_pdfs:

                result = self.vectorstore.get_by_source(
                    pdf_name,
                    limit=max_chunks_per_pdf
                )

                docs = result.get("documents", [])

                if docs:

                    contexts[pdf_name] = "\n\n".join(
                        docs[:max_chunks_per_pdf]
                    )

            return contexts

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return {}

    # ----------------------------------
    # HAS DOCUMENTS
    # ----------------------------------

    def has_documents(
        self
    ) -> bool:

        try:

            count = (
                self.vectorstore.count_documents()
            )

            print(
                f"Document Count: {count}"
            )

            return count > 0

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return False

    # ----------------------------------
    # DOCUMENT COUNT
    # ----------------------------------

    def count_documents(
        self
    ) -> int:

        try:

            return (
                self.vectorstore.count_documents()
            )

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return 0

    # ----------------------------------
    # GET ALL DOCUMENTS
    # ----------------------------------

    def get_all_documents(
        self
    ):

        try:

            return (
                self.vectorstore.get_all_documents()
            )

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )

            return {}

    # ----------------------------------
    # CLEAR DOCUMENTS
    # ----------------------------------

    def clear_documents(
        self
    ):

        try:

            self.vectorstore.delete_all()

            print(
                "All session documents deleted."
            )

        except RetrievalError:

            # A failed search must surface, not look like 'no results'.
            raise

        except Exception as e:

            print(
                f"Retriever Error: {e}"
            )