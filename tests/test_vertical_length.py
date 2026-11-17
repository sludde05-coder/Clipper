import asyncio
import subprocess

import clipper.vertical as v
from clipper.config import VerticalConfig
from clipper.transcribe import Transcript


def make_clip(path, seconds=8):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-f", "lavfi", "-i", "sine", "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", str(path)], check=True)


def render(tmp_path, monkeypatch, broken_passes):
    clip = tmp_path / "c.mp4"
    make_clip(clip)
    monkeypatch.setattr(v, "transcribe", lambda *a, **k: Transcript([]))
    real = v._encode
    calls = []

    async def flaky(clip, out, tmp, cfg, focus, safe):
        calls.append(safe)
        ok, err = await real(clip, out, tmp, cfg, focus, safe)
        if safe in broken_passes:   # simulate the "1 second" bug for this pass
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(out), "-t", "1", "-c", "copy",
                            str(out) + ".cut.mp4"], check=True)
            (out.parent / (out.name + ".cut.mp4")).replace(out)
        return ok, err

    monkeypatch.setattr(v, "_encode", flaky)
    v._slots = None
    out = asyncio.run(v.render_vertical(clip, VerticalConfig(ai_captions=False, speech_captions=False)))
    return out, calls


def test_normal_render_is_full_length(tmp_path, monkeypatch):
    out, calls = render(tmp_path, monkeypatch, broken_passes=())
    assert calls == [False]
    assert abs(v.probe_video_duration(out) - 8) < 0.5


def test_short_render_is_redone_in_safe_mode(tmp_path, monkeypatch):
    out, calls = render(tmp_path, monkeypatch, broken_passes=(False,))
    assert calls == [False, True]
    assert abs(v.probe_video_duration(out) - 8) < 0.5


def test_never_leaves_a_broken_clip(tmp_path, monkeypatch):
    out, calls = render(tmp_path, monkeypatch, broken_passes=(False, True))
    assert out is None and calls == [False, True]
    assert not (tmp_path / "c_vertical.mp4").exists()
