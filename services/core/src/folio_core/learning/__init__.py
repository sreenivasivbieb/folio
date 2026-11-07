"""Learning from corrections without training a model (proposal: "Human-in-the-loop").

* merge decisions become **aliases** (entity linking),
* rejected claims become **negative examples** and are blocked by fingerprint,
* verified/corrected claims become **few-shot examples** for the next extraction prompt,
* verified names become a **personal vocabulary** that biases speech recognition,
* the **acceptance rate** of proposed claims is measured per entity type over time.
"""

from .store import CorrectionStore, GazetteerEntry

__all__ = ["CorrectionStore", "GazetteerEntry"]
