import asyncio
import json
import subprocess

from aiohttp.test_utils import TestClient, TestServer

from clipper import naming
from clipper.app import ClipperApp
from clipper.config import VerticalConfig
from clipper.director import Beat, Plan
from clipper.transcribe import Word
from clipper.vertical import render_vertical

H = {"X-Clipper": "1"}


def make_library(tmp_path):
    clips = tmp_path / "clips"
    name = "KaiCenat_2026-11-19_21-34-12_1"
    src = clips / "KaiCenat" / naming.SOURCE / f"{name}.mp4"
    src.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-f", "lavfi", "-i", "sine", "-t", "6", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    det = clips / "KaiCenat" / naming.DETAILS / f"{name}.json"
    det.parent.mkdir(parents=True)
    det.write_text(json.dumps({"platform": "twitch", "name": "KaiCenat", "url": "https://www.twitch.tv/kaicenat",
                               "captions": {"post_caption": "Day one chaos #gta6"}}))
    phone = clips / "KaiCenat" / naming.PHONE / f"{name}.mp4"
    words = [Word(1 + i * 0.4, 1.35 + i * 0.4, w) for i, w in enumerate("okay watch this".split())]
    asyncio.run(render_vertical(src, VerticalConfig(), out=phone, meta_path=det,
                                plan=Plan(hook="Kai trusted the NPC", mood="funny", beats=[Beat(2, "WAIT")]), words=words))
    conf = tmp_path / "config.toml"
    conf.write_text(f'[clips]\noutput_dir = "{clips.as_posix()}"\n[post]\nfolder = "{(tmp_path / "POST").as_posix()}"\n'
                    '[phone]\nenabled = false\n', encoding="utf-8")
    return conf, phone, det, src


def run(conf, fn):
    async def go():
        app = ClipperApp(str(conf))
        async with TestClient(TestServer(app.make_app())) as c:
            return await fn(c, app)
    return asyncio.run(go())


def test_guard_blocks_other_sites(tmp_path):
    conf, *_ = make_library(tmp_path)

    async def fn(c, app):
        assert (await c.post("/api/quit")).status == 403                       # no app header: other website
        assert (await c.get("/api/clips", headers={"Host": "evil.example"})).status == 403
        assert (await c.get("/api/ping")).status == 200
    run(conf, fn)


def test_library_lists_streamers_and_clips(tmp_path):
    conf, phone, *_ = make_library(tmp_path)

    async def fn(c, app):
        d = await (await c.get("/api/clips")).json()
        assert [s["name"] for s in d["streamers"]] == ["KaiCenat"]
        clip = d["clips"][0]
        assert clip["hook"] == "Kai trusted the NPC" and clip["number"] == 1 and clip["time"] == "21:34:12"
        assert (await c.get(clip["thumb"])).status == 200
        r = await c.get(clip["video"], headers={"Range": "bytes=0-9"})
        assert r.status == 206
        detail = await (await c.get("/api/clip", params={"id": clip["id"]})).json()
        assert detail["can_rerender"] and detail["has_word_timings"] and detail["words_text"] == "okay watch this"
        assert "#fyp" in detail["post"]["tiktok"]["caption"]
    run(conf, fn)


def test_edit_post_captions_only_changed_platforms(tmp_path):
    conf, phone, det, _ = make_library(tmp_path)

    async def fn(c, app):
        cid = (await (await c.get("/api/clips")).json())["clips"][0]["id"]
        r = await c.post("/api/clip/post-captions", headers=H,
                         json={"id": cid, "post": {"tiktok": {"caption": "My own caption"}}})
        assert (await r.json())["post"]["tiktok"]["caption"] == "My own caption"
        d = await (await c.get("/api/clip", params={"id": cid})).json()
        assert d["post_edited"] == ["tiktok"] and "#reels" in d["post"]["instagram"]["caption"]
        await c.post("/api/clip/post-captions", headers=H, json={"id": cid, "reset": "tiktok"})
        d = await (await c.get("/api/clip", params={"id": cid})).json()
        assert d["post_edited"] == [] and d["post"]["tiktok"]["caption"] != "My own caption"
    run(conf, fn)


def test_rerender_with_edits(tmp_path):
    conf, phone, det, _ = make_library(tmp_path)
    before = phone.stat().st_mtime_ns

    async def fn(c, app):
        cid = (await (await c.get("/api/clips")).json())["clips"][0]["id"]
        r = await c.post("/api/clip/render", headers=H, json={
            "id": cid, "hook": "A brand new headline", "mood": "shock", "layout": "crop",
            "beats": [{"t": 3, "text": "NO WAY"}], "words_text": "okay watch THAT", "speech_on": True})
        assert r.status == 200
        for _ in range(240):
            job = await (await c.get("/api/clip/job", params={"id": cid})).json()
            if job["state"] != "running":
                break
            await asyncio.sleep(0.25)
        assert job["state"] == "done", job
    run(conf, fn)
    meta = json.loads(det.read_text())
    cap = meta["captions"]
    assert cap["hook"] == "A brand new headline" and cap["mood"] == "shock" and cap["layout"] == "crop"
    assert [w[2] for w in cap["words"]] == ["okay", "watch", "THAT"] and cap["words"][0][0] == 1.0
    assert phone.stat().st_mtime_ns != before and not list(phone.parent.glob("*.rendering.mp4"))


def test_posting_marks_and_cleans_up_original(tmp_path):
    conf, phone, det, src = make_library(tmp_path)

    async def fn(c, app):
        cid = (await (await c.get("/api/clips")).json())["clips"][0]["id"]
        await c.post("/api/clip/posted", headers=H, json={"id": cid, "platform": "tiktok"})
        await c.post("/api/clip/finish", headers=H, json={"id": cid})
        clip = (await (await c.get("/api/clips")).json())["clips"][0]
        assert clip["posted"] == {"tiktok": True, "youtube": False, "instagram": False}
        assert not (await (await c.get("/api/clip", params={"id": cid})).json())["can_rerender"]
    run(conf, fn)
    assert not src.exists() and phone.exists()


def test_delete_moves_to_deleted_clips(tmp_path):
    conf, phone, det, src = make_library(tmp_path)

    async def fn(c, app):
        cid = (await (await c.get("/api/clips")).json())["clips"][0]["id"]
        assert (await c.post("/api/clip/delete", headers=H, json={"id": cid})).status == 200
        assert (await (await c.get("/api/clips")).json())["clips"] == []
    run(conf, fn)
    bin_dir = tmp_path / "clips" / "Deleted clips" / "KaiCenat"
    assert sorted(p.name for p in bin_dir.iterdir()) == sorted(
        [phone.name, det.name, phone.stem + "_original.mp4"])


def test_clip_ids_cant_leave_the_clips_folder(tmp_path):
    conf, *_ = make_library(tmp_path)
    (tmp_path / "secret.mp4").write_bytes(b"x")

    async def fn(c, app):
        for bad in ("../secret.mp4", "KaiCenat/.source/KaiCenat_2026-11-19_21-34-12_1.mp4", "nope.mp4"):
            assert (await c.get("/media", params={"id": bad})).status == 404, bad
    run(conf, fn)


def test_settings_roundtrip(tmp_path):
    conf, *_ = make_library(tmp_path)

    async def fn(c, app):
        r = await c.post("/api/settings", headers=H, json={"values": [
            {"section": "discovery", "key": "platforms", "value": ["twitch"]},
            {"section": "discovery", "key": "languages", "value": []},
            {"section": "detector", "key": "multiplier", "value": "2.5"},
            {"section": "vertical", "key": "ai_model", "value": "claude-haiku-5-5"},
            {"section": "post", "key": "tiktok_tags", "value": "#gaming"},
            {"section": "nope", "key": "x", "value": "ignored"}]})
        assert r.status == 200
        f = {(x["section"], x["key"]): x["value"] for x in (await (await c.get("/api/settings")).json())["fields"]}
        assert f[("discovery", "platforms")] == ["twitch"] and f[("detector", "multiplier")] == 2.5
        assert app.cfg.post.tiktok_tags == "#gaming" and app.cfg.discovery.languages == []
    run(conf, fn)
    assert "nope" not in conf.read_text()


def test_bulk_delete_restore_and_delete_forever(tmp_path):
    conf, phone, det, src = make_library(tmp_path)
    second = phone.with_name("KaiCenat_2026-11-19_22-00-00_2.mp4")
    second.write_bytes(phone.read_bytes())
    (det.parent / (second.stem + ".json")).write_text(det.read_text())

    async def fn(c, app):
        ids = [x["id"] for x in (await (await c.get("/api/clips")).json())["clips"]]
        assert len(ids) == 2
        r = await (await c.post("/api/clip/delete", headers=H, json={"ids": ids})).json()
        assert r["deleted"] == 2 and (await (await c.get("/api/clips")).json())["clips"] == []

        binned = (await (await c.get("/api/deleted")).json())["clips"]
        assert sorted(b["number"] for b in binned) == [1, 2]
        assert (await c.get(binned[0]["thumb"])).status == 200

        first = next(b for b in binned if b["number"] == 1)
        r = await (await c.post("/api/deleted/restore", headers=H, json={"ids": [first["id"]]})).json()
        assert r["restored"] == 1
        back = (await (await c.get("/api/clips")).json())["clips"]
        assert len(back) == 1 and back[0]["hook"] == "Kai trusted the NPC"
        detail = await (await c.get("/api/clip", params={"id": back[0]["id"]})).json()
        assert detail["can_rerender"]                      # the hidden original came back too

        r = await (await c.post("/api/deleted/purge", headers=H, json={"all": True})).json()
        assert r["deleted"] == 1 and (await (await c.get("/api/deleted")).json())["clips"] == []
        # a clip outside Deleted clips can't be purged
        r = await (await c.post("/api/deleted/purge", headers=H, json={"ids": [back[0]["id"]]})).json()
        assert r["deleted"] == 0
    run(conf, fn)
    assert phone.exists() and src.exists() and not second.exists()
    assert not (tmp_path / "clips" / "Deleted clips" / "KaiCenat").exists()


def test_clips_being_made_failed_and_set_aside_are_reported(tmp_path, monkeypatch):
    conf, phone, det, src = make_library(tmp_path)
    root = tmp_path / "clips" / "KaiCenat"
    for folder, name in ((naming.WORK, "KaiCenat_2026-11-19_22-00-00_2"),
                         (naming.NOT_CONVERTED, "KaiCenat_2026-11-19_22-10-00_3"),
                         (naming.OTHER_LANGUAGES, "KaiCenat_2026-11-19_22-20-00_4")):
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / folder / f"{name}.mp4").write_bytes(src.read_bytes())
    (root / naming.WORK / "KaiCenat_2026-11-19_22-00-00_2.phone.mp4").write_bytes(b"half")  # ignored
    calls = []

    async def fake_finish(work, details, cfg):
        calls.append(work.name)
        return None
    import clipper.session
    monkeypatch.setattr(clipper.session, "finish_clip", fake_finish)

    async def fn(c, app):
        d = await (await c.get("/api/clips")).json()
        assert [m["number"] for m in d["making"]] == [2]
        assert [m["number"] for m in d["failed"]] == [3]
        assert [m["number"] for m in d["other_languages"]] == [4]
        r = await (await c.post("/api/clips/retry", headers=H, json={"clips": []})).json()
        assert r["retrying"] == 1
        await asyncio.sleep(0.2)
    run(conf, fn)
    assert calls == ["KaiCenat_2026-11-19_22-10-00_3.mp4"]
    assert (root / naming.WORK / "KaiCenat_2026-11-19_22-10-00_3.mp4").exists()
