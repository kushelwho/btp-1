"""Text embedders.

All embedders return L2-normalised float32 vectors, so a dot product is a
cosine similarity. The real embedder runs locally (no API cost, no network
after the first model download) and on CPU by default, because CPU inference
is deterministic — the same corpus always yields the same index.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def _normalise(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return (m / np.where(norms == 0, 1.0, norms)).astype(np.float32)


# Instruction prefixes some retrieval models expect on the *query* side only.
QUERY_PREFIXES = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
}


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str = "cpu", batch_size: int = 32):
        self.name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = None
        self._query_prefix = QUERY_PREFIXES.get(model_name, "")

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.name, device=self.device)
        return self._model

    @property
    def dim(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(texts, batch_size=self.batch_size, convert_to_numpy=True,
                                 normalize_embeddings=True, show_progress_bar=len(texts) > 256)
        return vecs.astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        vec = self.model.encode([self._query_prefix + text], convert_to_numpy=True, normalize_embeddings=True)
        return vec[0].astype(np.float32)


_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Deterministic bag-of-words embedder via feature hashing.

    For tests and offline development only — it captures lexical overlap,
    not meaning. Never use it for experiments.
    """

    def __init__(self, dim: int = 256):
        self.name = f"hashing-{dim}"
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _TOKEN.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalise(np.stack([self._vec(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return _normalise(self._vec(text)[None, :])[0]
