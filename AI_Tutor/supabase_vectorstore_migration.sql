-- ============================================================
-- Supabase / pgvector migration for AI Tutor's vector chunk store
-- ============================================================
-- Reconstructed from rag/vectorstore.py, rag/ingest.py, and
-- rag/retriever.py. The `document_chunks` table and
-- `match_document_chunks` function this app depends on already
-- exist and are live in production Supabase, but the migration
-- file referenced in vectorstore.py's own docstring
-- (supabase_vectorstore_migration.sql) was never checked into the
-- repo -- this file exists so the schema is reproducible (new
-- environment, disaster recovery, a teammate's Supabase project)
-- without reverse-engineering it from application code again.
--
-- Embedding dimension is 384, matching sentence-transformers'
-- "all-MiniLM-L6-v2" model (rag/embeddings.py). If that model is
-- ever changed to one with a different output size, VECTOR(384)
-- below and the ivfflat index must be rebuilt to match.
--
-- ASSUMPTION: session_id is UUID, matching Supabase's default
-- `sessions.id` primary key type (memory/session_manager.py treats
-- session_id as an opaque string throughout, so this could not be
-- confirmed from application code alone). Verify this against your
-- live `sessions` table before running; if it's TEXT instead,
-- change every `uuid` reference to `session_id` below to `text`.
--
-- No foreign key to sessions(id) is declared here. The application
-- code does NOT currently cascade-delete document_chunks when a
-- session is deleted (memory/session_manager.py's delete_session()
-- only touches selected_pdfs/pdfs/messages/sessions) -- adding an
-- enforced FK now would fail against any rows already orphaned by
-- that gap. Fixing that cleanup gap is a separate, deliberate
-- change, not something to slip in via a schema migration.
-- ============================================================

-- 1. Enable pgvector
create extension if not exists vector;

-- 2. document_chunks table
create table if not exists document_chunks (
    id          text primary key,          -- e.g. "{pdf_name}_chunk_{n}", see rag/ingest.py
    session_id  uuid not null,              -- see ASSUMPTION above
    source      text,                       -- original PDF filename
    page        integer,
    chunk_id    text,
    content     text not null,
    embedding   vector(384) not null,
    created_at  timestamptz not null default now()
);

-- 3. Indexes

-- Every read/write path filters by session_id first
-- (rag/vectorstore.py) -- this is the single most important index.
create index if not exists document_chunks_session_id_idx
    on document_chunks (session_id);

-- Speeds up the (session_id, source) delete-before-replace that
-- runs on every re-upload of a same-named PDF
-- (VectorStore.add_documents).
create index if not exists document_chunks_session_source_idx
    on document_chunks (session_id, source);

-- Approximate nearest-neighbor index for cosine similarity search.
-- `lists = 100` is a starting point for small/medium row counts --
-- see https://github.com/pgvector/pgvector#ivfflat for retuning
-- guidance as the table grows (roughly sqrt(row_count) is typical).
create index if not exists document_chunks_embedding_idx
    on document_chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- 4. match_document_chunks RPC
-- Called from rag/vectorstore.py's VectorStore.search(). Cosine
-- distance via the <=> operator -- matches the distance-math
-- documented in rag/retriever.py's module docstring
-- (distance = 1 - cosine_similarity, range [0, 2]).
create or replace function match_document_chunks (
    query_embedding vector(384),
    match_session_id uuid,
    match_source text default null,
    match_count int default 5
)
returns table (
    id text,
    content text,
    source text,
    page integer,
    chunk_id text,
    distance float
)
language sql stable
as $$
    select
        document_chunks.id,
        document_chunks.content,
        document_chunks.source,
        document_chunks.page,
        document_chunks.chunk_id,
        document_chunks.embedding <=> query_embedding as distance
    from document_chunks
    where document_chunks.session_id = match_session_id
      and (match_source is null or document_chunks.source = match_source)
    order by document_chunks.embedding <=> query_embedding
    limit match_count;
$$;
