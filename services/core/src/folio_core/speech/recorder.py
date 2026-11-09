"""Push-to-talk microphone capture in the core service (ADR-0003).

Capturing here instead of in the webview avoids WebKitGTK's patchy getUserMedia on Linux and
works the same on every OS. Audio is kept next to the database as the label's evidence.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import wave
from pathlib import Path

from ..domain.errors import Conflict, Unavailable

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
MAX_SECONDS = 120


def _sounddevice():  # type: ignore[no-untyped-def]
    """Import sounddevice, preferring a PortAudio bundled with a frozen Linux build (AppImage)."""
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "libportaudio.so.2"
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux") and bundled.exists():
        import ctypes.util

        original = ctypes.util.find_library
        ctypes.util.find_library = lambda name: str(bundled) if name == "portaudio" else original(name)
        try:
            import sounddevice
        finally:
            ctypes.util.find_library = original
        return sounddevice
    import sounddevice

    return sounddevice


class MicRecorder:
    def __init__(self) -> None:
        self._stream = None
        self._frames: list[bytes] = []
        self._lock = threading.Lock()
        self._started = 0.0
        self._rate = SAMPLE_RATE

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            sd = _sounddevice()
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
        sd = _sounddevice()

        with self._lock:
            if self._stream is not None:
                raise Conflict("already recording")
            self._frames = []

            def callback(indata, frames, t, status):  # type: ignore[no-untyped-def]
                if time.monotonic() - self._started < MAX_SECONDS:
                    self._frames.append(bytes(indata))

            # Record at the device's own rate: many devices (WASAPI on Windows, USB mics) reject
            # 16 kHz. The decoder resamples for Whisper.
            device = sd.query_devices(kind="input")
            self._rate = int(device.get("default_samplerate") or SAMPLE_RATE)
            stream = sd.RawInputStream(samplerate=self._rate, channels=1, dtype="int16", callback=callback)
            self._started = time.monotonic()
            try:
                stream.start()
            except Exception:
                stream.close()  # never leave a half-open stream marked as "recording"
                raise
            self._stream = stream

    def stop(self, dest: Path) -> float:
        """Stop and write a mono 16-bit WAV at the device rate. Returns the duration in seconds."""
        with self._lock:
            if self._stream is None:
                raise Conflict("not recording")
            stream, self._stream = self._stream, None  # released even if the device misbehaves
            frames, self._frames = self._frames, []
            try:
                stream.stop()
            except Exception as exc:  # unplugged mic, driver over/underrun
                log.warning("microphone stop failed: %s", exc)
            finally:
                try:
                    stream.close()
                except Exception as exc:
                    log.warning("microphone close failed: %s", exc)
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = b"".join(frames)
        with wave.open(str(dest), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._rate)
            w.writeframes(data)
        return len(data) / 2 / self._rate

    def cancel(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            self._frames = []
