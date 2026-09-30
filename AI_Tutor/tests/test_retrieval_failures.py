import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import api.chat as chat_api_module
import rag.vectorstore as vectorstore_module
import services.chat_api_service as chat_service_module
from auth.jwt_bearer import CurrentUser, get_current_user
from main import app
from models.errors import RetrievalError
from rag.retriever import Retriever

from tests.test_orchestrator_routing import _intents
from tests.test_pdf_retrieval_routing import _orch_with


DB_SECRET_DETAIL = "connection to db.internal:5432 failed (password auth)"


def _store():

    with patch.object(vectorstore_module, "EmbeddingModel"), \
         patch.object(vectorstore_module.VectorStore, "count_documents",
                      return_value=1):
        store = vectorstore_module.VectorStore(session_id="s")

    store.embedder = MagicMock()
    store.embedder.embed_query.return_value = [0.0] * 384

    return store


class TestVectorStoreFailures:

    def test_search_failure_raises_instead_of_empty_result(self):

        store = _store()
        fake = MagicMock()
        fake.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            SimpleNamespace(count=3)
        )
        fake.rpc.return_value.execute.side_effect = RuntimeError(DB_SECRET_DETAIL)

        with patch.object(vectorstore_module, "supabase", fake):
            with pytest.raises(RetrievalError) as err:
                store.search("q", pdf_name="a.pdf")

        # Server-side detail is kept for logs; the user message is safe.
        assert DB_SECRET_DETAIL in str(err.value)
        assert DB_SECRET_DETAIL not in err.value.user_message

    def test_count_failure_raises_instead_of_zero(self):

        store = _store()
        fake = MagicMock()
        fake.table.return_value.select.return_value.eq.return_value.execute.side_effect = (
            RuntimeError(DB_SECRET_DETAIL)
        )

        with patch.object(vectorstore_module, "supabase", fake):
            with pytest.raises(RetrievalError):
                store.count_documents()

    def test_constructor_survives_count_failure(self):

        with patch.object(vectorstore_module, "EmbeddingModel"), \
             patch.object(vectorstore_module.VectorStore, "count_documents",
                          side_effect=RetrievalError("down")):
            vectorstore_module.VectorStore(session_id="s")


class TestRetrieverSeparatesNoResultsFromFailure:

    def _retriever(self, search):

        with patch("rag.retriever.VectorStore"):
            retriever = Retriever(session_id="s")

        retriever.vectorstore.search = search
        retriever.vectorstore.keyword_search = MagicMock(
            return_value={"documents": [], "ids": [], "metadatas": [], "embeddings": []}
        )

        return retriever

    def test_no_relevant_chunks_is_empty_not_error(self):

        retriever = self._retriever(MagicMock(return_value={
            "documents": ["unrelated"], "ids": ["1"], "distances": [0.95],
            "metadatas": [{"source": "a.pdf"}]
        }))

        result = retriever.get_context_with_sources("capital of France", selected_pdfs=["a.pdf"])

        assert result == {"context": "", "sources": []}

    def test_search_failure_propagates(self):

        retriever = self._retriever(MagicMock(side_effect=RetrievalError("down")))

        with pytest.raises(RetrievalError):
            retriever.get_context_with_sources("q", selected_pdfs=["a.pdf"])

        with pytest.raises(RetrievalError):
            retriever.get_grouped_context_by_source("q", selected_pdfs=["a.pdf"])


class TestOrchestratorRetrievalFailure:

    def test_explicit_pdf_question_does_not_answer_when_search_failed(self):

        orch = _orch_with(_intents(answer=True))
        orch.retriever.get_context_with_sources = MagicMock(
            side_effect=RetrievalError("down")
        )

        with pytest.raises(RetrievalError):
            orch.run("According to the PDF, what is X?", selected_pdfs=["a.pdf"])

        orch.tutor.generate_answer.assert_not_called()

    def test_has_documents_failure_is_not_treated_as_no_documents(self):

        orch = _orch_with(_intents(answer=True))
        orch.retriever.has_documents = MagicMock(side_effect=RetrievalError("down"))

        with pytest.raises(RetrievalError):
            orch.run("how does it work", selected_pdfs=["a.pdf"])

        orch.tutor.generate_answer.assert_not_called()


class TestApiSurfacesSafeRetrievalError:

    @pytest.fixture(autouse=True)
    def _auth(self):

        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u")
        yield

    def test_chat_returns_503_with_safe_message(self):

        client = TestClient(app)

        with patch.object(
            chat_api_module.chat_api_service, "run",
            side_effect=RetrievalError(DB_SECRET_DETAIL)
        ):
            r = client.post("/api/chat/", json={"session_id": "s", "query": "q"})

        assert r.status_code == 503
        assert "couldn't search your selected PDF" in r.json()["detail"]
        assert "5432" not in r.text

    def test_stream_sends_safe_error_frame(self):

        client = TestClient(app)
        orch = MagicMock()
        orch.run_stream.side_effect = RetrievalError(DB_SECRET_DETAIL)

        with patch.object(chat_service_module, "load_orchestrator", return_value=orch):
            r = client.post("/api/chat/stream", json={"session_id": "s", "query": "q"})

        frames = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
        assert frames[-1]["type"] == "error"
        assert "couldn't search your selected PDF" in frames[-1]["message"]
        assert "5432" not in r.text

    def test_unexpected_error_does_not_leak_details(self):

        client = TestClient(app)

        with patch.object(
            chat_api_module.chat_api_service, "run",
            side_effect=ValueError(DB_SECRET_DETAIL)
        ):
            r = client.post("/api/chat/", json={"session_id": "s", "query": "q"})

        assert r.status_code == 500
        assert "5432" not in r.text
