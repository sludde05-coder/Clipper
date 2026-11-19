"""The AI editing team, end to end on a real video, with a fake AI giving each editor an answer."""
import asyncio
import json
import subprocess

import pytest

import clipper.director as director
import clipper.editors as editors
import clipper.vertical as v
from clipper.config import VerticalConfig
from clipper.poster import captions_for
from clipper.transcribe import Transcript, Word


def capture(path, seconds=40):
    """A 1920x1080 'stream': moving gameplay with a solid green webcam box in the top-left corner."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=d={seconds}",
                    "-vf", "drawbox=x=40:y=40:w=480:h=270:color=0x00ff00:t=fill",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)


def fake_ai(calls, review=None):
    async def ask(model, messages, schema=None):
        req = schema or director.SCHEMA
        calls.append(req)
        if req is editors.TRIM_SCHEMA:
            return {"start": 8, "end": 24, "why": "he sets up the jump and lands it"}
        if req is editors.FACECAM_SCHEMA:
            return {"has_facecam": True, "x": 40 / 1920, "y": 40 / 1080, "w": 480 / 1920, "h": 270 / 1080, "action_x": 0.6}
        if req is editors.POST_SCHEMA:
            return {"tiktok": "kai really landed that 😭 would you have tried it?", "instagram": "kai landed it.",
                    "youtube_title": "he actually landed that", "youtube_description": "gta 6 day one.",
                    "hashtags": ["#gta6", "#kaicenat"]}
        if req is editors.REVIEW_SCHEMA:
            return review or {"ok": True, "issues": [], "new_hook": "", "layout": "keep", "drop_beats": False}
        return {"hook_options": ["a", "b", "c"], "hook": "he was NOT ready for that jump", "mood": "hype",
                "beats": [{"t": 6, "text": "WAIT FOR IT"}], "emphasis": [], "crop_focus_x": 0.5,
                "post_caption": "x #gta6"}
    return ask


@pytest.fixture()
def clip(tmp_path, monkeypatch):
    src = tmp_path / "Kai_2026-11-19_21-34-12_1.mp4"
    capture(src)
    words = [Word(10 + i * 0.5, 10.4 + i * 0.5, w) for i, w in enumerate("okay watch this jump".split())]
    monkeypatch.setattr(v, "transcribe", lambda *a, **k: Transcript(words, "en", 0.99))
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"name": "KaiCenat", "platform": "twitch", "explosion_offset": 18,
                                "chat_timeline": [[17 + i * 0.1, f"u{i}", "KEKW"] for i in range(40)]}), encoding="utf-8")
    v._slots = None
    return src, meta


def run(src, meta, cfg, monkeypatch, review=None):
    calls = []
    ask = fake_ai(calls, review)
    monkeypatch.setattr(editors, "_ask", ask)
    monkeypatch.setattr(director, "_ask", ask)
    out = src.with_name("phone.mp4")
    res = asyncio.run(v.render_vertical(src, cfg, out=out, meta_path=meta, trim_window=(22, 8)))
    return res, calls, json.loads(meta.read_text(encoding="utf-8"))


def pixel(path, t, x, y):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                         capture_output=True).stdout
    return tuple(raw[:3])


def test_full_team_trims_puts_webcam_on_top_and_writes_texts(clip, monkeypatch):
    src, meta_path = clip
    out, calls, meta = run(src, meta_path, VerticalConfig(), monkeypatch)
    assert out and out.exists()
    # 5 editors asked: trim, webcam, captions, post, review
    assert set(map(id, calls)) == {id(s) for s in (editors.TRIM_SCHEMA, editors.FACECAM_SCHEMA, director.SCHEMA,
                                                  editors.POST_SCHEMA, editors.REVIEW_SCHEMA)}
    # trimmed to 8-24 s of the 40 s recording, timings shifted with it
    assert abs(v.probe_video_duration(out) - 16) < 0.5
    assert meta["trim"]["by"] == "ai" and meta["explosion_offset"] == 10
    assert meta["captions"]["words"][0][0] == 2.0
    # webcam on top: the top of the phone clip is the green webcam box
    assert meta["captions"]["layout"] == "facecam"
    r, g, b = pixel(out, 3, 540, 150)
    assert g > 200 and r < 80 and b < 80, (r, g, b)
    # post editor's texts are used, with the streamer credit added
    caps = captions_for(meta, out)
    assert caps["tiktok"]["caption"].startswith("kai really landed that") and "🎥 KaiCenat on Twitch" in caps["tiktok"]["caption"]
    assert caps["youtube"]["title"] == "he actually landed that | KaiCenat #shorts"


def test_review_editor_fixes_get_applied(clip, monkeypatch):
    src, meta_path = clip
    review = {"ok": False, "issues": ["the top shows no face"], "new_hook": "he sent it with zero hesitation",
              "layout": "blur", "drop_beats": True}
    out, _, meta = run(src, meta_path, VerticalConfig(), monkeypatch, review=review)
    cap = meta["captions"]
    assert cap["hook"] == "he sent it with zero hesitation" and cap["layout"] == "blur" and cap["beats"] == []
    assert meta["review"]["issues"] == ["the top shows no face"]


def test_without_ai_the_clip_is_the_usual_window(clip, monkeypatch):
    src, meta_path = clip
    out, calls, meta = run(src, meta_path, VerticalConfig(ai_captions=False), monkeypatch)
    assert calls == []
    # explosion at 18 s: 22 s before is clipped by the start of the recording, 8 s after -> 0-26 s
    assert abs(v.probe_video_duration(out) - 26) < 0.5 and meta["trim"]["by"] == "default"
    assert meta["captions"]["layout"] == "blur"


def test_trim_answer_is_kept_sane():
    # must include the explosion, between 10 and 50 s, inside the recording
    t = editors.Trim(0, 0)
    assert editors.MIN_LEN == 10 and editors.MAX_LEN == 50 and t.source == "default"
    g = v.facecam_geometry([0.02, 0.04, 0.25, 0.25], 1920, 1080, 0.5)
    assert g["ht"] + g["hb"] == 1920 and 480 <= g["ht"] <= 800
    cw, ch, cx, cy = g["cam"]
    gw, gh, gx, gy = g["game"]
    assert cx + cw <= 1920 and cy + ch <= 1080 and gx + gw <= 1920 and gy + gh <= 1080
    assert abs(cw / ch - 1080 / g["ht"]) < 0.02 and abs(gw / gh - 1080 / g["hb"]) < 0.02


def test_cover_is_the_headline_over_the_best_moment(clip, monkeypatch, tmp_path):
    from clipper.cover import cover_path, make_cover
    src, meta_path = clip
    out, _, meta = run(src, meta_path, VerticalConfig(), monkeypatch)
    phone = tmp_path / "Kai" / "Phone clips" / out.name
    phone.parent.mkdir(parents=True)
    out.replace(phone)
    cover = cover_path(tmp_path, phone)
    assert cover == tmp_path / ".covers" / f"Kai__{phone.stem}.jpg"
    # from the caption-free original: webcam on top, like the clip
    assert asyncio.run(make_cover(phone, cover, meta, VerticalConfig(), source=src)) == cover
    assert v.probe_size(cover) == (1080, 1920)
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(cover), "-vf", "crop=2:2:540:150",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True).stdout
    r, g, b = tuple(raw[:3])
    assert g > 200 and r < 80 and b < 80, (r, g, b)
    # made again only when the clip changes
    made = cover.stat().st_mtime_ns
    assert asyncio.run(make_cover(phone, cover, meta, VerticalConfig(), source=src)) == cover
    assert cover.stat().st_mtime_ns == made
    # without the original, a frame of the phone clip itself
    cover.unlink()
    assert asyncio.run(make_cover(phone, cover, meta, VerticalConfig(), source=None)) == cover
    assert v.probe_size(cover) == (1080, 1920)


def test_webcam_on_top_with_the_whole_screen_below(clip, monkeypatch):
    src, meta_path = clip
    out, _, meta = run(src, meta_path, VerticalConfig(layout="facecam_full"), monkeypatch)
    assert meta["captions"]["layout"] == "facecam_full" and v.probe_size(out) == (1080, 1920)
    g = v.facecam_geometry(meta["captions"]["facecam"], 1920, 1080, 0.5, full=True)
    assert g["vh"] == 608 and g["ht"] + g["hb"] == 1920
    top = g["ht"] + (g["hb"] - g["vh"]) // 2
    r, gr, b = pixel(out, 3, 540, 150)                  # webcam on top
    assert gr > 200 and r < 80 and b < 80, (r, gr, b)
    r, gr, b = pixel(out, 3, 150, top + 100)            # ...and the whole screen below: its webcam corner shows too
    assert gr > 200 and r < 80 and b < 80, (r, gr, b)
    assert v.resolve_layout("facecam_full", None) == "blur"
