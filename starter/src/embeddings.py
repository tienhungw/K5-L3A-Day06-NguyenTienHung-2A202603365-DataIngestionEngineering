"""Local embedding model (sentence-transformers). Errors are raised, never replaced by mock vectors."""
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class E5Embedder:
    """intfloat/multilingual-e5-* models: "query: " / "passage: " prefixes, L2-normalized output."""

    def __init__(self, model_name: str, revision: str | None = None,
                 device: str = "cpu", batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.revision = revision
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, revision=revision, device=device)
        self.dimensions = self.model.get_embedding_dimension()
        self.max_seq_length = self.model.max_seq_length
        config = getattr(self.model[0], "auto_model", None)
        self.resolved_revision = getattr(getattr(config, "config", None), "_commit_hash", None) or revision

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                    convert_to_numpy=True, show_progress_bar=False)
        if vectors.shape != (len(texts), self.dimensions):
            raise RuntimeError(f"unexpected embedding shape {vectors.shape}")
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" for t in texts]) if texts else []

    def embed_query(self, question: str) -> list[float]:
        return self._encode([f"query: {question}"])[0]

    def token_counts(self, texts: list[str], prefix: str = "passage: ") -> list[int]:
        tokenizer = self.model.tokenizer
        return [len(tokenizer(prefix + t, add_special_tokens=True)["input_ids"]) for t in texts]
