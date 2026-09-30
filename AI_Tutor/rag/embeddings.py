from sentence_transformers import SentenceTransformer


class EmbeddingModel:

    _model = None

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2"
    ):
        """
        Initialize embedding model.
        """

        if EmbeddingModel._model is None:

            print(
                f"Loading embedding model: {model_name}"
            )

            EmbeddingModel._model = (
                SentenceTransformer(model_name)
            )

        self.model = EmbeddingModel._model

    def embed_documents(
        self,
        documents: list[str]
    ) -> list[list[float]]:
        """
        Generate embeddings for document chunks.
        """

        embeddings = self.model.encode(
            documents,
            convert_to_numpy=True,
            normalize_embeddings=True
        )

        return embeddings.tolist()

    def embed_query(
        self,
        query: str
    ) -> list[float]:
        """
        Generate embedding for user query.
        """

        embedding = self.model.encode(
            query,
            convert_to_numpy=True,
            normalize_embeddings=True
        )

        return embedding.tolist()

    def get_dimension(
        self
    ) -> int:
        """
        Return embedding dimension.
        """

        sample = self.embed_query(
            "test query"
        )

        return len(sample)