"""Persistent vector store on Chroma (PersistentClient, HNSW index, cosine distance).

The starter targets PostgreSQL + pgvector; this machine has no Docker, so the same
interface is implemented on Chroma, which GUIDE.md lists as an accepted store.
"""
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from .models import Chunk

FILTER_FIELDS = {"year", "document_id", "chapter", "section", "article"}
BATCH = 1000


class ChromaStore:
    def __init__(self, path: Path, model_name: str, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.path = Path(path)
        self.model_name = model_name
        self.dimensions = dimensions
        self.client = chromadb.PersistentClient(path=str(self.path),
                                                settings=Settings(anonymized_telemetry=False))
        self._collections = {}

    def create_schema(self, name: str):
        """Get or create a collection; refuse to mix vectors from another model."""
        if name in self._collections:
            return self._collections[name]
        collection = self.client.get_or_create_collection(
            name=name,
            embedding_function=None,
            metadata={
                "hnsw:space": "cosine",
                "hnsw:construction_ef": 200,
                "hnsw:search_ef": 100,
                "embedding_model": self.model_name,
                "dimensions": self.dimensions,
            },
        )
        meta = collection.metadata or {}
        if meta.get("embedding_model") != self.model_name or meta.get("dimensions") != self.dimensions:
            raise RuntimeError(f"collection {name} was built with {meta.get('embedding_model')} "
                               f"({meta.get('dimensions')} dims), not {self.model_name}")
        if meta.get("hnsw:space") != "cosine":
            raise RuntimeError(f"collection {name} does not use cosine distance")
        self._collections[name] = collection
        return collection

    def existing(self, name: str) -> dict[str, dict]:
        """chunk_id -> stored metadata, for every item in the collection."""
        got = self.create_schema(name).get(include=["metadatas"])
        return dict(zip(got["ids"], got["metadatas"]))

    def update_metadata(self, name: str, chunks: list[Chunk]) -> None:
        collection = self.create_schema(name)
        for i in range(0, len(chunks), BATCH):
            part = chunks[i:i + BATCH]
            collection.update(ids=[c.chunk_id for c in part],
                              metadatas=[self._metadata(c) for c in part])

    @staticmethod
    def _metadata(chunk: Chunk) -> dict:
        return {**chunk.metadata, "document_id": chunk.document_id, "source": chunk.source,
                "page": chunk.page}

    def count(self, name: str) -> int:
        return self.create_schema(name).count()

    def delete(self, name: str, ids: list[str]) -> None:
        collection = self.create_schema(name)
        for i in range(0, len(ids), BATCH):
            collection.delete(ids=ids[i:i + BATCH])

    def upsert(self, name: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk ids in one upsert")
        bad = [c.chunk_id for c, v in zip(chunks, vectors) if len(v) != self.dimensions]
        if bad:
            raise ValueError(f"wrong vector size for {bad[:3]}")
        collection = self.create_schema(name)
        for i in range(0, len(chunks), BATCH):
            part = chunks[i:i + BATCH]
            collection.upsert(
                ids=[c.chunk_id for c in part],
                embeddings=vectors[i:i + BATCH],
                documents=[c.text for c in part],
                metadatas=[self._metadata(c) for c in part],
            )

    def search(self, name: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Top-k by cosine distance; `filters` is an exact-match dict on allowed metadata fields."""
        if len(query_vector) != self.dimensions:
            raise ValueError("query vector has the wrong size")
        where = None
        if filters:
            unknown = set(filters) - FILTER_FIELDS
            if unknown:
                raise ValueError(f"filter fields not allowed: {sorted(unknown)}")
            clauses = [{k: v} for k, v in filters.items()]
            where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
        res = self.create_schema(name).query(query_embeddings=[query_vector], n_results=top_k,
                                             where=where,
                                             include=["documents", "metadatas", "distances"])
        return [
            {"chunk_id": cid, "text": doc, "distance": dist, "score": 1.0 - dist, "metadata": meta}
            for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0],
                                            res["metadatas"][0], res["distances"][0])
        ]
