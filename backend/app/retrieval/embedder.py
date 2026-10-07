import logging
import threading
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return L2-normalised float32 vectors, one row per text."""


class FastEmbedEmbedder:
    """Local ONNX sentence embeddings (no GPU, no API key). Model loads lazily on first use."""

    def __init__(self, model_name: str, max_chars: int = 320):
        self.name = model_name.split("/")[-1]
        self._model_name = model_name
        self._max_chars = max_chars
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        vectors = np.asarray(
            list(self._load().embed([t[: self._max_chars] for t in texts], batch_size=64)), dtype=np.float32
        )
        return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9, None)


def create_embedder(kind: str, model_name: str) -> Embedder | None:
    """Returns None when dense embeddings are unavailable; callers fall back to lexical vectors."""
    if kind != "fastembed":
        return None
    try:
        import fastembed  # noqa: F401
    except ImportError:
        log.warning("fastembed not installed; using lexical similarity only")
        return None
    return FastEmbedEmbedder(model_name)
