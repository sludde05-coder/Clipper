import subprocess
from types import SimpleNamespace

import numpy as np

from clipper import transcribe as t


def test_audio_goes_to_whisper_as_decoded_samples(tmp_path, monkeypatch):
    """Whisper gets ready-made audio, so its own (PyAV-based) decoder is never used."""
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
                    "-f", "lavfi", "-i", "sine", "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", str(clip)], check=True)
    got = {}

    class FakeModel:
        def transcribe(self, audio, **kw):
            got["audio"] = audio
            word = SimpleNamespace(start=0.5, end=0.9, word=" hello")
            return [SimpleNamespace(words=[word])], SimpleNamespace(language="en", language_probability=0.97)

    monkeypatch.setitem(t._models, "fake", FakeModel())
    tr = t.transcribe(clip, "fake")
    assert isinstance(got["audio"], np.ndarray) and got["audio"].dtype == np.float32
    assert abs(got["audio"].size - 2 * t.SAMPLE_RATE) < 1000
    assert [w.text for w in tr.words] == ["hello"] and tr.language == "en"


def test_clip_without_sound_gives_no_words(tmp_path, monkeypatch):
    clip = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
                    "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", str(clip)], check=True)
    monkeypatch.setitem(t._models, "fake", object())   # would crash if it were called
    assert t.transcribe(clip, "fake").words == []
