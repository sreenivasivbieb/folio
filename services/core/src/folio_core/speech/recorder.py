"""Push-to-talk microphone capture in the core service (ADR-0003).

Capturing here instead of in the webview avoids WebKitGTK's patchy getUserMedia on Linux and
works the same on every OS. Audio is kept next to the database as the label's evidence.
"""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

from ..domain.errors import Conflict, Unavailable

SAMPLE_RATE = 16_000
MAX_SECONDS = 120


class MicRecorder:
    def __init__(self) -> None:
        self._stream = None
        self._frames: list[bytes] = []
        self._lock = threading.Lock()
        self._started = 0.0

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import sounddevice as sd

            sd.query_devices(kind="input")
            return True, "ok"
        except ImportError:
            return False, "sounddevice not installed (folio-core[speech])"
        except Exception as exc:
            return False, f"no input device: {exc}"

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        ok, reason = self.available()
        if not ok:
            raise Unavailable(f"microphone unavailable: {reason}")
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                raise Conflict("already recording")
            self._frames = []

            def callback(indata, frames, t, status):  # type: ignore[no-untyped-def]
                if time.monotonic() - self._started < MAX_SECONDS:
                    self._frames.append(bytes(indata))

            self._stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                             callback=callback)
            self._started = time.monotonic()
            self._stream.start()

    def stop(self, dest: Path) -> float:
        """Stop and write a 16 kHz mono WAV. Returns the duration in seconds."""
        with self._lock:
            if self._stream is None:
                raise Conflict("not recording")
            self._stream.stop()
            self._stream.close()
            self._stream = None
            frames, self._frames = self._frames, []
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = b"".join(frames)
        with wave.open(str(dest), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(data)
        return len(data) / 2 / SAMPLE_RATE

    def cancel(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            self._frames = []
