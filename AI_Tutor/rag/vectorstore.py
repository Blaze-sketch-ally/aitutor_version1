import uuid

from database.supabase_client import supabase
from models.errors import RetrievalError
from models.metrics import record_store_call
from rag.embeddings import EmbeddingModel


class VectorStore:
    """
    Supabase/pgvector-backed replacement for the old ChromaDB
    VectorStore. Kept the SAME public method signatures and return
    shapes as the ChromaDB version on purpose — Retriever and
    PDFIngestor call these methods without knowing or caring which
    storage backend is behind them, so neither of those files needed
    any changes for this migration.

    Requires the SQL migration (supabase_vectorstore_migration.sql)
    to have been run first — this creates the `document_chunks` table
    and the `match_document_chunks` similarity-search function.
    """

    def __init__(
        self,
        session_id: str = None
    ):

        if session_id is None:

            session_id = str(uuid.uuid4())

        self.session_id = session_id
        self.embedder = EmbeddingModel()

        # No database call here: this is built on every chat request, and
        # the document count it used to print cost a round trip each time.
        print(f"VectorStore ready (session {self.session_id})")

    # ----------------------------------
    # ADD DOCUMENTS
    # ----------------------------------

    # ----------------------------------
    # CHUNK IDENTITY
    # ----------------------------------
    # document_chunks.id is a GLOBAL primary key. It used to be
    # "{pdf_name}_chunk_{n}", so two sessions (or two users) uploading
    # the same filename upserted over each other's rows. Chunk ids are
    # now "{session_id}:{document_id}:{n}" — session_id isolates
    # sessions/users, and document_id (a fresh uuid per upload)
    # isolates one upload of a file from the next re-upload of the
    # same name, which is what lets add_documents() insert the new
    # version BEFORE removing the old one. Legacy rows keep their old
    # ids and stay searchable (all reads filter on session_id/source,
    # never on the id format).

    @staticmethod
    def new_document_id() -> str:

        return uuid.uuid4().hex

    def chunk_id_prefix(self, document_id: str) -> str:

        return f"{self.session_id}:{document_id}:"

    def make_chunk_id(self, document_id: str, index: int) -> str:

        return f"{self.chunk_id_prefix(document_id)}{index}"

    def add_documents(
        self,
        chunks: list[str],
        ids: list[str],
        metadatas: list[dict] | None = None,
        document_id: str | None = None
    ):
        """
        Embeds and inserts chunks. RAISES on any embedding/insert
        failure — callers (PDFIngestor -> api/pdf.py) must not report a
        successful upload when nothing was stored.

        With document_id (ids built via make_chunk_id): new rows are
        inserted first, and only after every batch succeeded are older
        rows for the same (session_id, source) removed. A failed insert
        rolls back its own partial rows and leaves the previous version
        of the PDF intact.

        Without document_id (legacy callers): old delete-then-insert
        replace behaviour, but still raising on failure.
        """

        if not ids or not chunks:

            raise ValueError("No chunks to add.")

        if len(ids) != len(chunks):

            raise ValueError("ids and chunks must be the same length.")

        sources = {
            m.get("source")
            for m in (metadatas or [])
            if m.get("source")
        }

        if document_id is None:

            # Legacy path — replace first, same as before.
            for source in sources:

                (
                    supabase
                    .table("document_chunks")
                    .delete()
                    .eq("session_id", self.session_id)
                    .eq("source", source)
                    .execute()
                )

        embeddings = self.embedder.embed_documents(chunks)

        if len(embeddings) != len(chunks):

            raise RuntimeError(
                f"Embedding count mismatch: {len(embeddings)} "
                f"embeddings for {len(chunks)} chunks."
            )

        rows = []

        for i, chunk_id in enumerate(ids):

            metadata = metadatas[i] if metadatas else {}

            rows.append({
                "id": chunk_id,
                "session_id": self.session_id,
                "source": metadata.get("source"),
                "page": metadata.get("page"),
                "chunk_id": metadata.get("chunk_id"),
                "content": chunks[i],
                "embedding": embeddings[i]
            })

        # Batch insert in chunks of 200 — avoids one giant request
        # for large PDFs and keeps payload size reasonable.
        batch_size = 200

        try:

            for i in range(0, len(rows), batch_size):

                batch = rows[i:i + batch_size]

                (
                    supabase
                    .table("document_chunks")
                    .upsert(batch)
                    .execute()
                )

        except Exception:

            if document_id is not None:

                self.delete_document(document_id)

            raise

        # --------------------------------------
        # REPLACE OLD CHUNKS FOR THE SAME SOURCE
        # --------------------------------------
        # Re-uploading a PDF with the same filename in the same session
        # fully replaces its prior content. Scoped to this session only,
        # and to rows NOT belonging to the upload just inserted.

        if document_id is not None:

            for source in sources:

                (
                    supabase
                    .table("document_chunks")
                    .delete()
                    .eq("session_id", self.session_id)
                    .eq("source", source)
                    .not_.like("id", f"{self.chunk_id_prefix(document_id)}%")
                    .execute()
                )

        print(f"Added {len(rows)} chunks.")

    # ----------------------------------
    # DELETE ONE UPLOADED DOCUMENT
    # ----------------------------------
    # Removes only the rows of one upload (by its chunk-id prefix) —
    # used to roll back a failed/abandoned ingestion without touching
    # any other version of the same filename. Best-effort: logs rather
    # than raises, since it runs on error paths.

    def delete_document(self, document_id: str) -> bool:

        try:

            (
                supabase
                .table("document_chunks")
                .delete()
                .eq("session_id", self.session_id)
                .like("id", f"{self.chunk_id_prefix(document_id)}%")
                .execute()
            )

            return True

        except Exception as e:

            print(f"Delete Document Error ({document_id}): {e}")
            return False

    # ----------------------------------
    # SEARCH
    # ----------------------------------

    def search(
        self,
        query: str,
        n_results: int = 4,
        pdf_name: str | None = None
    ):

        record_store_call("search")

        try:

            # No pre-count: an empty session simply returns no rows from
            # the RPC, and callers already check has_documents() once.
            print(f"Searching session: {self.session_id}")

            query_embedding = self.embedder.embed_query(query)

            print("\n========== FILTER DEBUG ==========")
            print("Requested PDF:", pdf_name)
            print("===================================\n")

            result = (
                supabase
                .rpc(
                    "match_document_chunks",
                    {
                        "query_embedding": query_embedding,
                        "match_session_id": self.session_id,
                        "match_source": pdf_name,
                        "match_count": n_results
                    }
                )
                .execute()
            )

            rows = result.data or []

            documents = [row["content"] for row in rows]
            distances = [row["distance"] for row in rows]
            ids = [row["id"] for row in rows]
            metadatas = [
                {
                    "source": row.get("source"),
                    "page": row.get("page"),
                    "chunk_id": row.get("chunk_id")
                }
                for row in rows
            ]

            print(f"Retrieved {len(documents)} chunks")
            print(f"Distances: {distances}")

            return {
                "documents": documents,
                "ids": ids,
                "distances": distances,
                "metadatas": metadatas
            }

        except Exception as e:

            # A FAILED search is not "no results" — callers must be able
            # to tell the difference (see models.errors.RetrievalError).
            print(f"Search Error (session={self.session_id}): {e}")

            raise RetrievalError(
                f"match_document_chunks failed "
                f"(session={self.session_id}): {e}"
            ) from e

    # ----------------------------------
    # KEYWORD SEARCH (exact substring, no embeddings)
    # ----------------------------------
    # Lets the Retriever find chunks containing an exact identifier from
    # the query (codes, ids, formula names) that dense similarity ranks
    # poorly. Returns the same shape as search(), minus distances —
    # the caller scores them.

    def keyword_search(
        self,
        term: str,
        pdf_name: str | None = None,
        limit: int = 5
    ):

        empty = {"documents": [], "ids": [], "metadatas": [], "embeddings": []}

        record_store_call("keyword_search")

        try:

            # PostgREST's ilike treats % and _ as wildcards; escape
            # them so "ALPHA_UNIQUE" matches literally.
            escaped = (
                term.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )

            query = (
                supabase
                .table("document_chunks")
                .select("id, content, source, page, chunk_id, embedding")
                .eq("session_id", self.session_id)
                .ilike("content", f"%{escaped}%")
            )

            if pdf_name:
                query = query.eq("source", pdf_name)

            rows = query.limit(limit).execute().data or []

            return {
                "documents": [row["content"] for row in rows],
                "ids": [row["id"] for row in rows],
                "metadatas": [
                    {
                        "source": row.get("source"),
                        "page": row.get("page"),
                        "chunk_id": row.get("chunk_id")
                    }
                    for row in rows
                ],
                "embeddings": [row.get("embedding") for row in rows]
            }

        except Exception as e:

            print(f"Keyword Search Error: {e}")
            return empty

    # ----------------------------------
    # COUNT DOCUMENTS
    # ----------------------------------

    def count_documents(self):

        record_store_call("count_documents")

        try:

            result = (
                supabase
                .table("document_chunks")
                .select("id", count="exact")
                .eq("session_id", self.session_id)
                .execute()
            )

            return result.count or 0

        except Exception as e:

            # Returning 0 here used to make has_documents() False, which
            # silently skipped retrieval altogether on a DB failure.
            print(f"Count Documents Error (session={self.session_id}): {e}")

            raise RetrievalError(
                f"count_documents failed (session={self.session_id}): {e}"
            ) from e

    # ----------------------------------
    # GET BY SOURCE (no similarity search)
    # ----------------------------------
    # Same purpose as the ChromaDB version: pull a PDF's own content
    # directly via metadata filter, no embedding/similarity involved.

    def get_by_source(self, source: str, limit: int | None = None):

        record_store_call("get_by_source")

        try:

            query = (
                supabase
                .table("document_chunks")
                .select("content, source, page, chunk_id")
                .eq("session_id", self.session_id)
                .eq("source", source)
            )

            if limit:
                query = query.limit(limit)

            result = query.execute()

            rows = result.data or []

            return {
                "documents": [row["content"] for row in rows],
                "metadatas": [
                    {
                        "source": row.get("source"),
                        "page": row.get("page"),
                        "chunk_id": row.get("chunk_id")
                    }
                    for row in rows
                ]
            }

        except Exception as e:

            print(f"Get By Source Error (session={self.session_id}): {e}")

            raise RetrievalError(
                f"get_by_source failed (session={self.session_id}): {e}"
            ) from e

    # ----------------------------------
    # DELETE ALL DOCUMENTS (this session only)
    # ----------------------------------

    def delete_all(self):

        try:

            (
                supabase
                .table("document_chunks")
                .delete()
                .eq("session_id", self.session_id)
                .execute()
            )

            print(f"Deleted all documents for session {self.session_id}.")

        except Exception as e:

            print(f"Delete Error: {e}")

    # ----------------------------------
    # GET ALL DOCUMENTS
    # ----------------------------------

    def get_all_documents(self):

        try:

            result = (
                supabase
                .table("document_chunks")
                .select("id, content, source, page, chunk_id")
                .eq("session_id", self.session_id)
                .execute()
            )

            rows = result.data or []

            return {
                "ids": [row["id"] for row in rows],
                "documents": [row["content"] for row in rows],
                "metadatas": [
                    {
                        "source": row.get("source"),
                        "page": row.get("page"),
                        "chunk_id": row.get("chunk_id")
                    }
                    for row in rows
                ]
            }

        except Exception as e:

            print(f"Get Documents Error: {e}")
            return {}

    # ----------------------------------
    # DELETE COLLECTION
    # ----------------------------------
    # No separate "collection" concept in the Supabase table model —
    # this is just an alias for delete_all(), kept as its own method
    # so any existing caller of delete_collection() doesn't break.

    def delete_collection(self):

        self.delete_all()
        print(f"Deleted collection (session) {self.session_id}.")

    # ----------------------------------
    # LIST COLLECTIONS
    # ----------------------------------
    # Returns distinct session_ids that currently have chunks stored.

    def list_collections(self):

        try:

            result = (
                supabase
                .table("document_chunks")
                .select("session_id")
                .execute()
            )

            rows = result.data or []

            return sorted({row["session_id"] for row in rows})

        except Exception as e:

            print(f"List Collections Error: {e}")
            return []