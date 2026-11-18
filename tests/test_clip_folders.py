import asyncio
import time
from pathlib import Path

import aiohttp

import clipper.session as s
from clipper.config import Config
from clipper.detector import Spike
from clipper.models import Stream


class FakeRecorder:
    async def save_clip(self, start, end, out):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"original")
        return start


def run_clip(tmp_path, monkeypatch, phone_ok=True, keep=False, vertical=True):
    cfg = Config()
    cfg.clips.output_dir = str(tmp_path / "clips")
    cfg.clips.pre_roll, cfg.clips.post_roll, cfg.clips.segment_seconds = 1, 0, 0
    cfg.clips.keep_originals = keep
    cfg.vertical.enabled = vertical

    async def fake_render(clip, vcfg, out=None, **kw):
        if not phone_ok:
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"phone")
        return out

    monkeypatch.setattr(s, "render_vertical", fake_render)

    async def go():
        async with aiohttp.ClientSession() as http:
            sess = s.ChannelSession(Stream("twitch", "kai", "u", display_name="KaiCenat"), cfg, http,
                                    chat=iter(()))
            sess.recorder = FakeRecorder()
            now = time.time() - 5
            await sess._clip(Spike(detected_at=now, onset=now, rate=10, baseline=1, zscore=9))

    asyncio.run(go())
    root = tmp_path / "clips" / "KaiCenat"
    return {str(p.relative_to(root)).replace("\\", "/").split("/")[0] for p in root.rglob("*") if p.is_file()
            and not p.name.startswith(".clip-count")}


def test_phone_clip_made_original_kept_hidden_for_edits(tmp_path, monkeypatch):
    assert run_clip(tmp_path, monkeypatch) == {"Phone clips", "Captions and details", ".source"}


def test_failed_phone_version_keeps_original(tmp_path, monkeypatch):
    assert run_clip(tmp_path, monkeypatch, phone_ok=False) == {"Not converted", "Captions and details"}


def test_keep_originals_setting(tmp_path, monkeypatch):
    assert run_clip(tmp_path, monkeypatch, keep=True) == {"Phone clips", "Captions and details", "Originals"}


def test_phone_versions_off_keeps_original(tmp_path, monkeypatch):
    assert run_clip(tmp_path, monkeypatch, vertical=False) == {"Originals", "Captions and details"}
