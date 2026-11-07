from __future__ import annotations

import hashlib
import re

import numpy as np

_TOKEN = re.compile(r"\w+", re.UNICODE)


class HashingEmbedder:
    """Zero-download embedder: signed feature hashing of words and character trigrams.

    It captures lexical and fuzzy-spelling similarity ("Acme Corp" ~ "ACME Corporation"), which is
    enough for entity resolution and for hybrid retrieval to work fully offline out of the box.
    Swap in ``fastembed`` (``FOLIO_EMBEDDER=fastembed``) for real semantic embeddings.
    """

    is_local = True

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.model_id = f"hashing-v1-{dim}"

    def _features(self, text: str) -> list[str]:
        words = [w.lower() for w in _TOKEN.findall(text)]
        feats = [f"w:{w}" for w in words]
        for w in words:
            padded = f"#{w}#"
            feats += [f"c:{padded[i:i + 3]}" for i in range(len(padded) - 2)]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for feat in self._features(text):
                h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")
                out[row, h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
            norm = np.linalg.norm(out[row])
            if norm:
                out[row] /= norm
        return out
