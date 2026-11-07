from __future__ import annotations

from typing import Protocol

import numpy as np


class Embedder(Protocol):
    model_id: str
    dim: int
    is_local: bool

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) float32 array of L2-normalised vectors."""
        ...
