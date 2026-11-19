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
            {"section": "post", "key": "pause_between_clips", "value": "480"},
            {"section": "post", "key": "pause_between_clips_max", "value": "600"},
            {"section": "nope", "key": "x", "value": "ignored"}]})
        assert r.status == 200
        f = {(x["section"], x["key"]): x["value"] for x in (await (await c.get("/api/settings")).json())["fields"]}
        assert f[("discovery", "platforms")] == ["twitch"] and f[("detector", "multiplier")] == 2.5
        assert app.cfg.post.tiktok_tags == "#gaming" and app.cfg.discovery.languages == []
        posting = await (await c.get("/api/settings")).json()
        assert (posting["pause_between_clips"], posting["pause_between_clips_max"]) == (480, 600)
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


def test_block_button_stops_the_streamer_and_saves_it(tmp_path):
    import tomllib
    from clipper.models import Stream
    from clipper.orchestrator import Orchestrator
    conf, *_ = make_library(tmp_path)
    stopped = []

    class FakeSession:
        def __init__(self, st):
            self.stream = st

        async def stop(self):
            stopped.append(self.stream.key)

    async def fn(c, app):
        app.orch = Orchestrator(app.cfg)
        for st in (Stream("twitch", "kaicenat", "u", 9, "", "KaiCenat"), Stream("twitch", "xqc", "u", 8, "", "xQc")):
            app.orch.sessions[st.key] = FakeSession(st)
        r = await (await c.post("/api/block", headers=H, json={"name": "KaiCenat"})).json()
        assert r["blocked"] == ["KaiCenat"]
        assert stopped == ["twitch:kaicenat"] and list(app.orch.sessions) == ["twitch:xqc"]
        assert app.orch.refresh_now.is_set()                       # looks for a replacement right away
        assert (await (await c.get("/api/state")).json())["blocked"] == ["KaiCenat"]
        r = await (await c.post("/api/block", headers=H, json={"name": "kaicenat", "block": False})).json()
        assert r["blocked"] == []
    run(conf, fn)
    assert tomllib.loads(conf.read_text(encoding="utf-8"))["discovery"]["blocked"] == []


def test_top5_needs_at_least_two_clips(tmp_path):
    conf, *_ = make_library(tmp_path)

    async def fn(c, app):
        r = await c.post("/api/compilation", headers=H, json={"ids": [], "title": "x"})
        assert r.status == 400 and "at least 2" in (await r.json())["error"]
    run(conf, fn)


def test_scheduled_post_goes_to_every_platform(tmp_path):
    from datetime import datetime, timedelta

    from clipper import schedule
    conf, phone, *_ = make_library(tmp_path)

    async def fn(c, app):
        app.cfg.post.autofill = app.cfg.post.autosubmit = True
        app.cfg.post.platforms = ["tiktok", "youtube"]
        done = []

        async def fake_post(clip, platform, caps, status, submit):
            status("Posting")
            done.append((clip.name, platform, submit))
            return {"state": "posted", "error": "", "message": "ok"}
        app._post_one = fake_post
        cid = app._id(phone)
        schedule.add(app.clips_dir, cid, datetime.now() - timedelta(minutes=1), "Kai")
        for item in schedule.due(app.clips_dir):
            await app._post_scheduled(item)
        assert done == [(phone.name, "tiktok", True), (phone.name, "youtube", True)]
        items = (await (await c.get("/api/schedule")).json())["items"]
        assert items[0]["state"] == "posted"
        # with "Also click Post for me" off, it's not posted and says why
        app.cfg.post.autosubmit = False
        schedule.add(app.clips_dir, cid, datetime.now() - timedelta(minutes=1), "Kai again")
        for item in schedule.due(app.clips_dir):
            await app._post_scheduled(item)
        last = [i for i in schedule.load(app.clips_dir) if i["label"] == "Kai again"][0]
        assert last["state"] == "failed" and "Also click Post for me" in last["message"]
    run(conf, fn)


def test_phone_app_gets_the_whole_library_with_its_key(tmp_path):
    from clipper.phone import PhoneServer
    conf, phone, *_ = make_library(tmp_path)

    async def go():
        app = ClipperApp(str(conf))
        app.cfg.phone.key = "k1"
        server = PhoneServer(app.cfg, None, library=app)
        async with TestClient(TestServer(server.app())) as c:
            assert (await c.get("/lib/clips")).status == 403                    # no key: refused
            K = {"X-Clipper-Key": "k1"}
            page = await (await c.get("/?k=k1")).text()
            assert "/lib/clips" in page                                          # the library page, not the POST folder one
            info = await (await c.get("/api/info", headers=K)).json()
            assert info["library"] is True and info["platforms"]
            clips = (await (await c.get("/lib/clips", headers=K)).json())["clips"]
            assert [x["name"] for x in clips] == [phone.stem]
            cid = clips[0]["id"]
            detail = await (await c.get(f"/lib/clip?id={cid}", headers=K)).json()
            assert detail["post"]["tiktok"]["caption"] and detail["cover"].startswith("/api/cover")
            # the video and its cover load with the key in the address (as <video>/<img> do), and can be saved
            r = await c.get(detail["video"] + "&k=k1&download=1&name=clip.mp4")
            assert r.status == 200 and "attachment" in r.headers["Content-Disposition"]
            assert (await c.get(detail["cover"] + "&k=k1")).status == 200
            # mark posted, then delete (to the Deleted clips bin, like on the PC)
            assert (await c.post("/lib/clip/posted", headers=K, json={"id": cid, "platform": "tiktok", "posted": True})).status == 200
            assert app._meta(phone)["posted"]["tiktok"]
            assert (await c.post("/lib/clip/delete", headers=K, json={"ids": [cid]})).status == 200
            assert not phone.exists() and (app.clips_dir / "Deleted clips" / "KaiCenat" / phone.name).exists()
            # anything else of the PC app isn't reachable from the phone
            assert (await c.post("/api/quit", headers=K)).status in (404, 405)
    asyncio.run(go())



def test_failed_and_other_language_recordings_can_be_deleted(tmp_path):
    conf, phone, *_ = make_library(tmp_path)
    root = phone.parent.parent
    failed = root / naming.NOT_CONVERTED / "KaiCenat_2026-11-19_22-00-00_2.mp4"
    other = root / naming.OTHER_LANGUAGES / "KaiCenat_2026-11-19_23-00-00_3.mp4"
    for f in (failed, other):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 1000)
    (root / naming.DETAILS / (failed.stem + ".json")).write_text("{}")
    other.with_suffix(".json").write_text("{}")

    async def fn(c, app):
        lists = await (await c.get("/api/clips")).json()
        assert len(lists["failed"]) == 1 and len(lists["other_languages"]) == 1
        r = await (await c.post("/api/clips/discard", headers=H, json={"which": "failed"})).json()
        assert r["deleted"] == 1 and not failed.exists() and not (root / naming.DETAILS / (failed.stem + ".json")).exists()
        r = await (await c.post("/api/clips/discard", headers=H, json={"which": "other", "streamer": "KaiCenat"})).json()
        assert r["deleted"] == 1 and not other.exists() and not other.with_suffix(".json").exists()
        assert phone.exists()                                         # finished clips aren't touched
        assert (await c.post("/api/clips/discard", headers=H, json={"which": "everything"})).status == 400
    run(conf, fn)



def test_stuck_clips_can_be_deleted_but_not_ones_being_made(tmp_path):
    from clipper import progress
    conf, phone, *_ = make_library(tmp_path)
    work = phone.parent.parent / naming.WORK
    work.mkdir(exist_ok=True)
    stuck = work / "KaiCenat_2026-11-19_22-00-00_2.mp4"
    busy = work / "KaiCenat_2026-11-19_22-10-00_3.mp4"
    for f in (stuck, busy):
        f.write_bytes(b"x" * 1000)
    (work / (stuck.stem + ".rendering.mp4")).write_bytes(b"x")
    (phone.parent.parent / naming.DETAILS / (stuck.stem + ".json")).write_text("{}")
    progress.step(busy.name, "Rendering the video")          # being made right now
    try:
        async def fn(c, app):
            making = (await (await c.get("/api/clips")).json())["making"]
            assert {m["name"] for m in making} == {stuck.stem, busy.stem}
            r = await (await c.post("/api/clips/discard", headers=H, json={"which": "stuck"})).json()
            assert r["deleted"] == 1 and not stuck.exists() and busy.exists()
            assert not (work / (stuck.stem + ".rendering.mp4")).exists()
            assert not (phone.parent.parent / naming.DETAILS / (stuck.stem + ".json")).exists()
        run(conf, fn)
    finally:
        progress.done(busy.name)



def test_dull_clips_are_found_and_listed_first(tmp_path, monkeypatch):
    from clipper import dullcheck
    conf, phone, det, _ = make_library(tmp_path)
    second = phone.with_name("KaiCenat_2026-11-19_22-00-00_2.mp4")
    second.write_bytes(phone.read_bytes())
    (det.parent / (second.stem + ".json")).write_text(det.read_text())
    seen = []

    async def fake_ask(model, messages, schema=None):
        assert schema is dullcheck.SCHEMA
        text = messages[0]["content"][-1]["text"]
        seen.append(sum(1 for x in messages[0]["content"] if x["type"] == "image"))
        assert "Chat across the clip" in text and "Video check" in text
        dull = len(seen) == 1
        return {"what_happens": "He drives around" if dull else "He crashes into a train", "score": 1 if dull else 8,
                "verdict": "trash" if dull else "keep", "why": "Just driving, nothing happens" if dull else "Big crash"}
    monkeypatch.setattr(dullcheck, "_ask", fake_ask)

    async def fn(c, app):
        r = await (await c.post("/api/dull/scan", headers=H, json={})).json()
        assert r["total"] == 2
        for _ in range(100):
            res = await (await c.get("/api/dull")).json()
            if res["job"]["state"] == "done":
                break
            await asyncio.sleep(0.2)
        assert [x["verdict"] for x in res["clips"]] == ["trash", "keep"]       # dull ones first
        assert res["clips"][0]["why"] == "Just driving, nothing happens"
        assert seen == [dullcheck.FRAMES, dullcheck.FRAMES]                       # looked across the whole clip
        # a second scan only looks at new clips
        r = await (await c.post("/api/dull/scan", headers=H, json={})).json()
        assert r["total"] == 0
    run(conf, fn)


def test_frozen_or_black_video_is_dull_without_ai(tmp_path, monkeypatch):
    from clipper import dullcheck
    clip = tmp_path / "black.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:size=320x568:rate=30:d=12",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)

    async def no_ai(*a, **k):
        raise AssertionError("the AI isn't needed for a black clip")
    monkeypatch.setattr(dullcheck, "_ask", no_ai)
    v = asyncio.run(dullcheck.check(clip, {}, "m"))
    assert v["verdict"] == "trash" and v["by"] == "video" and v["video"]["black"] >= 10
