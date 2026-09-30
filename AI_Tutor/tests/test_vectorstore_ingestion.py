from unittest.mock import MagicMock, patch

import pytest

import rag.vectorstore as vectorstore_module


def _store(session_id="11111111-1111-1111-1111-111111111111"):

    with patch.object(vectorstore_module, "EmbeddingModel"), \
         patch.object(vectorstore_module.VectorStore, "count_documents",
                      return_value=0):
        store = vectorstore_module.VectorStore(session_id=session_id)

    store.embedder = MagicMock()
    store.embedder.embed_documents.side_effect = (
        lambda docs: [[0.0] * 384 for _ in docs]
    )

    return store


class TestChunkIdentity:

    def test_chunk_ids_are_scoped_to_session_and_document(self):

        a = _store("aaaaaaaa-0000-0000-0000-000000000000")
        b = _store("bbbbbbbb-0000-0000-0000-000000000000")

        doc = a.new_document_id()

        # Same filename/doc id/index in two sessions must never collide
        # on the table's global primary key.
        assert a.make_chunk_id(doc, 0) != b.make_chunk_id(doc, 0)
        assert a.make_chunk_id(doc, 0).startswith(a.session_id)

    def test_each_upload_gets_a_fresh_document_id(self):

        store = _store()

        assert store.new_document_id() != store.new_document_id()


class TestAddDocumentsFailures:

    def test_insert_failure_raises_and_rolls_back_partial_rows(self):

        store = _store()
        doc = store.new_document_id()

        fake_supabase = MagicMock()
        fake_supabase.table.return_value.upsert.return_value.execute.side_effect = (
            RuntimeError("insert failed")
        )

        with patch.object(vectorstore_module, "supabase", fake_supabase), \
             patch.object(store, "delete_document") as mock_delete:

            with pytest.raises(RuntimeError, match="insert failed"):
                store.add_documents(
                    chunks=["x"],
                    ids=[store.make_chunk_id(doc, 0)],
                    metadatas=[{"source": "a.pdf"}],
                    document_id=doc
                )

        mock_delete.assert_called_once_with(doc)
        # The previous version must not have been deleted.
        fake_supabase.table.return_value.delete.assert_not_called()

    def test_embedding_failure_raises(self):

        store = _store()
        store.embedder.embed_documents.side_effect = RuntimeError("no model")

        with pytest.raises(RuntimeError, match="no model"):
            store.add_documents(
                chunks=["x"],
                ids=["id"],
                metadatas=[{"source": "a.pdf"}],
                document_id="doc"
            )

    def test_empty_input_raises(self):

        with pytest.raises(ValueError):
            _store().add_documents(chunks=[], ids=[])
