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


def test_chat_with_emoji_and_other_scripts_is_saved(tmp_path, monkeypatch):
    """The details file holds raw chat; it must save whatever people type."""
    import json
    from clipper.models import ChatMessage
    cfg_root = tmp_path

    class Chatty(FakeRecorder):
        pass

    def patched(sess):
        now = time.time() - 5
        for i, text in enumerate(["KEKW 😂😂", "ㅋㅋㅋㅋ", "мда", "no way 💀", "¿qué?", "x​\ud83d"[:-1]]):
            sess.recent.append(ChatMessage(f"u{i}", text, now + 0.1 * i))

    real_init = s.ChannelSession.__init__

    def init(self, *a, **k):
        real_init(self, *a, **k)
        patched(self)

    monkeypatch.setattr(s.ChannelSession, "__init__", init)
    folders = run_clip(cfg_root, monkeypatch)
    assert "Phone clips" in folders
    details = next((cfg_root / "clips" / "KaiCenat" / "Captions and details").glob("*.json"))
    text = details.read_text(encoding="utf-8")
    assert "😂" in text and "ㅋㅋ" in text and "мда" in text


def test_unfinished_clip_is_recovered(tmp_path, monkeypatch):
    from clipper import naming

    cfg = s.Config()
    cfg.clips.output_dir = str(tmp_path / "clips")
    work = tmp_path / "clips" / "KaiCenat" / naming.WORK
    work.mkdir(parents=True)
    (work / "KaiCenat_2026-11-19_21-34-12_1.mp4").write_bytes(b"original")
    (work / "KaiCenat_2026-11-19_21-34-12_1.phone.mp4").write_bytes(b"half")   # left over from a crash
    details = tmp_path / "clips" / "KaiCenat" / naming.DETAILS
    details.mkdir(parents=True)
    (details / "KaiCenat_2026-11-19_21-34-12_1.json").write_text('{\n  "platform": "twi', encoding="utf-8")  # cut off

    async def fake_render(clip, vcfg, out=None, **kw):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"phone")
        return out

    monkeypatch.setattr(s, "render_vertical", fake_render)
    assert asyncio.run(s.recover_unfinished(cfg)) == 1
    root = tmp_path / "clips" / "KaiCenat"
    assert (root / "Phone clips" / "KaiCenat_2026-11-19_21-34-12_1.mp4").exists()
    assert (root / ".source" / "KaiCenat_2026-11-19_21-34-12_1.mp4").exists()
    import json
    meta = json.loads((root / "Captions and details" / "KaiCenat_2026-11-19_21-34-12_1.json").read_text(encoding="utf-8"))
    assert meta["recovered"] and meta["name"] == "KaiCenat"
    assert list(work.iterdir()) == []
