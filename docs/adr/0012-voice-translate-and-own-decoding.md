# 0012 — Voice: translate to English offline; decode audio ourselves; cross-platform capture

**Status.** Accepted (product owner's decision for Hindi/Hinglish, 2026-11-09).

**Context.** Real-hardware testing found voice labelling broken end to end: faster-whisper
1.2.1 calls PyAV with an argument PyAV 19 removed, so *every* transcription crashed (unit
tests used a fake transcriber and could not see it). Media indexing also required a system
`ffmpeg`, which Windows machines usually lack. The label grammar is English, while the
product owner speaks Hindi/Hinglish. A desktop hotkey on Wayland (`folio-core voice toggle`)
did not know what the UI had selected, and its preview never opened in the UI.

**Decision.**

* **Translate, offline.** Voice labels are transcribed with Whisper's `task="translate"`, so any
  spoken language reaches the English grammar as English. No network, no LLM needed (chosen
  over an LLM-based parser). The grammar learned the shapes translations produce ("the
  contract of Acme", "Priya is its owner") and open-schema types ("it is a Course").
* **Our own decoding.** `providers/stt/audio.py` decodes with PyAV (bundled FFmpeg libraries on
  every OS) and resamples to 16 kHz; Whisper receives samples, never a path. Untrusted media
  is decoded in a resource-limited child process; our own recordings in-process.
* **Capture at the device rate.** The recorder uses the input device's native sample rate
  (WASAPI and many USB mics reject 16 kHz). PortAudio comes from the sounddevice wheel on
  Windows and is bundled into the Linux sidecar for the AppImage.
* **Latency.** The model is loaded at start-up and right after download; labels use beam 3.
  Measured on CPU (Whisper small): ~3 s from end of speech to preview, down from ~6 s.
* **Correctable.** The preview's transcript is editable and re-planned ("PREA" → "Priya").
* **Hotkeys.** The UI reports its selection (`/api/voice/focus`); a target-less toggle labels
  it, and the label's SSE event opens the preview in the UI.

**Consequences.** Labels are stored in English (the original audio is kept as evidence).
Media transcripts keep their original language (best for search). Windows needs no extra
installs for voice or media.
