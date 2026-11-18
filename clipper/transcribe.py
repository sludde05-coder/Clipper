"""Speech-to-text with word timestamps (faster-whisper, runs locally on CPU or GPU).

Optional: if faster-whisper isn't installed, clips get no speech captions.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
_models: dict[str, object] = {}
_lock = threading.Lock()
SAMPLE_RATE = 16000  # what Whisper expects


def load_audio(path: Path):
    """The clip's sound as 16 kHz mono floats, decoded with ffmpeg.

    faster-whisper can decode files itself, but through PyAV, whose newer versions no longer
    accept an option faster-whisper passes ("metadata_errors"). Handing it ready-made audio
    avoids that whole dependency."""
    import numpy as np
    from .proc import NO_WINDOW
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn",
                        "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
                       capture_output=True, **NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg couldn't read the audio: " + r.stderr.decode(errors="replace")[-200:])
    return np.frombuffer(r.stdout, dtype=np.float32)


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    words: list[Word]
    language: str | None = None       # e.g. "en", as detected by Whisper
    language_probability: float = 0.0


def transcribe(path: Path, model_size: str = "small") -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("faster-whisper not installed: no speech captions (pip install faster-whisper)")
        return Transcript([])
    with _lock:  # one model per size, shared, and whisper isn't thread-safe
        try:
            if model_size not in _models:
                from . import progress
                progress.step(path.name, "Getting the speech-to-text model ready (first time downloads ~500 MB)")
                log.info("loading whisper model %r (first time downloads it)", model_size)
                _models[model_size] = WhisperModel(model_size, device="auto", compute_type="int8")
                progress.step(path.name, "Listening to what the streamer says")
            audio = load_audio(path)
            if audio.size < SAMPLE_RATE // 2:
                return Transcript([])  # no sound track (or under half a second)
            segments, info = _models[model_size].transcribe(audio, word_timestamps=True, vad_filter=True)
            words = [Word(w.start, w.end, w.word.strip())
                     for seg in segments for w in (seg.words or []) if w.word.strip()]
            return Transcript(words, info.language, info.language_probability)
        except Exception as e:  # noqa: BLE001 - captions are a bonus; never lose the clip over them
            log.warning("transcription failed (%s): no speech captions for %s", e, path.name)
            return Transcript([])
