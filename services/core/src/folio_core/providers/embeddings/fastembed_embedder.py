from __future__ import annotations

import numpy as np

from ...domain.errors import Unavailable


class FastEmbedEmbedder:
    """Local ONNX Runtime text embeddings (``pip install folio-core[embeddings]``).

    The model downloads once on first use, then runs fully offline.
    """

    is_local = True

    def __init__(self, model: str, cache_dir: str | None = None) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise Unavailable("fastembed is not installed (folio-core[embeddings])") from exc
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)
        self.model_id = model
        self.dim = len(next(iter(self._model.embed(["probe"]))))

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.array(list(self._model.embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.where(norms == 0, 1, norms)
