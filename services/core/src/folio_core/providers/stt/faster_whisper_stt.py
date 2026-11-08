from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from ...domain.errors import Unavailable
from .base import Progress, Segment

# Approximate download sizes (MB) so the UI can say what a download costs.
MODEL_SIZES_MB = {"tiny": 75, "base": 145, "small": 484, "medium": 1530, "large-v3": 3090}
_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


class FasterWhisperTranscriber:
    """Local Whisper on CPU (int8) with Silero voice-activity detection.

    Privacy: this class never downloads on its own. ``installed()`` checks the local cache;
    ``download()`` is called only by the explicit "download speech model" job the user starts.
    After that it runs fully offline. Multilingual models handle Hindi/English mixes.
    """

    is_local = True

    def __init__(self, model: str = "small", download_root: str | None = None) -> None:
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            raise Unavailable("faster-whisper is not installed (folio-core[speech])") from exc
        self.model_id = f"faster-whisper-{model}"
        self.size = model
        self.size_mb = MODEL_SIZES_MB.get(model, 0)
        self._root = download_root
        self._model = None
        self._lock = threading.Lock()

    def _repo_id(self) -> str:
        from faster_whisper.utils import _MODELS

        return _MODELS.get(self.size, self.size)

    def installed(self) -> bool:
        from faster_whisper.utils import download_model

        try:
            download_model(self.size, local_files_only=True, cache_dir=self._root)
            return True
        except Exception:
            return False

    def download(self, on_progress: Callable[[float, str], None] | None = None) -> None:
        """Fetch the model (explicit user action). Progress = bytes on disk / expected size."""
        from huggingface_hub import snapshot_download

        done = threading.Event()
        repo_id = self._repo_id()
        cache = Path(self._root) if self._root else Path.home() / ".cache" / "huggingface" / "hub"
        root = cache / f"models--{repo_id.replace('/', '--')}"

        def watch() -> None:
            expected = max(self.size_mb, 1) * 1024 * 1024
            while not done.wait(1.0):
                have = sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.exists() else 0
                if on_progress:
                    on_progress(min(have / expected, 0.99), f"downloading {have // (1024 * 1024)} / ~{self.size_mb} MB")

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            snapshot_download(repo_id, cache_dir=self._root, allow_patterns=_FILES)
        finally:
            done.set()
            watcher.join(timeout=2)

    def _load(self):  # type: ignore[no-untyped-def]
        with self._lock:
            if self._model is None:
                if not self.installed():
                    raise Unavailable(f"speech model '{self.size}' is not downloaded yet")
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.size, device="auto", compute_type="int8",
                                           download_root=self._root, local_files_only=True)
        return self._model

    def transcribe(
        self, audio_path: Path, language: str | None = None, prompt: str | None = None,
        on_progress: Progress | None = None,
    ) -> list[Segment]:
        segments, info = self._load().transcribe(
            str(audio_path), language=language, initial_prompt=prompt, vad_filter=True, beam_size=5,
        )
        out: list[Segment] = []
        last = 0.0
        for s in segments:  # a generator: transcription happens while we iterate
            out.append(Segment(start=s.start, end=s.end, text=s.text.strip()))
            if on_progress and info.duration and time.monotonic() - last > 1.0:
                last = time.monotonic()
                on_progress(min(s.end / info.duration, 1.0))
        return out
