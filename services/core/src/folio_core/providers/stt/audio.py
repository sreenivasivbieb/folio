"""Audio decoding for speech-to-text: any audio/video file -> 16 kHz mono float32.

Why our own decoder: faster-whisper's built-in ``decode_audio`` breaks with newer PyAV releases
(it passes an argument PyAV 19 removed), and calling a system ``ffmpeg`` binary does not work on
Windows machines that don't have one. PyAV ships its own FFmpeg libraries in the wheel on Linux,
Windows and macOS, so decoding needs nothing installed.

Untrusted media files are decoded in a resource-limited child process (see
``decode_untrusted``), like every other parser. Our own push-to-talk recordings are decoded
in-process.

Child entry point: ``python -I -m folio_core.providers.stt.audio <src> <dst.npy> <memory-mb>``
(or ``folio-core decode-audio ...`` in a frozen build).
"""

from __future__ import annotations

import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

from ...domain.errors import Unavailable

SAMPLE_RATE = 16_000


def resample(audio: np.ndarray, rate: int) -> np.ndarray:
    """Linear resampling to 16 kHz — plenty for speech recognition."""
    if rate == SAMPLE_RATE or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    n = int(round(audio.size * SAMPLE_RATE / rate))
    x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def load_wav(path: Path) -> np.ndarray:
    """Our own 16-bit PCM recordings, at whatever rate the microphone delivered."""
    with wave.open(str(path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        return load_media(path)
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return resample(audio, rate)


def load_media(path: Path) -> np.ndarray:
    """Decode the first audio stream of any container (mp3, m4a, mp4, mkv, webm, wav, ...)."""
    try:
        import av
    except ImportError as exc:  # pragma: no cover - comes with the speech extra
        raise Unavailable("audio decoding needs PyAV (folio-core[speech])") from exc
    chunks: list[np.ndarray] = []
    with av.open(str(path), mode="r") as container:
        if not container.streams.audio:
            raise Unavailable(f"{path.name} has no audio track")
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def decode_untrusted(src: Path, dst: Path, timeout_s: int, memory_mb: int) -> np.ndarray:
    """Decode a user file in a child process (crash/timeout/memory contained)."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "decode-audio", str(src), str(dst), str(memory_mb)]
    else:
        cmd = [sys.executable, "-I", "-m", "folio_core.providers.stt.audio", str(src), str(dst), str(memory_mb)]
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TMP", "TEMP", "TMPDIR")
    env = {k: v for k, v in os.environ.items() if k in keep} | {
        k: "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s, env=env, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise Unavailable(f"decoding audio timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        tail = " ".join(proc.stderr.decode(errors="replace").strip().splitlines()[-2:])
        raise Unavailable(f"cannot decode the audio: {tail or f'exit code {proc.returncode}'}")
    return np.load(dst)


def child_main(argv: list[str]) -> int:
    src, dst, memory_mb = Path(argv[0]), Path(argv[1]), int(argv[2])
    if sys.platform != "win32":
        import resource

        limit = memory_mb * 1024 * 1024
        # RLIMIT_DATA (Linux >= 4.7 counts private writable memory incl. anonymous mmaps) caps
        # what a parser can allocate. RLIMIT_AS also counted reserved-but-unused address space
        # (glibc arenas, BLAS buffers, mapped libraries), which could crash the child at import.
        limit_kind = getattr(resource, "RLIMIT_DATA", resource.RLIMIT_AS)
        resource.setrlimit(limit_kind, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    np.save(dst, load_media(src))
    return 0


if __name__ == "__main__":
    raise SystemExit(child_main(sys.argv[1:]))
