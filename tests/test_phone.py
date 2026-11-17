import asyncio
import json
import subprocess
import tomllib

from aiohttp.test_utils import TestClient, TestServer

from clipper.config import Config
from clipper.phone import PhoneServer, ensure_key

META = {"platform": "twitch", "channel": "kaicenat", "name": "KaiCenat", "url": "https://www.twitch.tv/kaicenat",
        "captions": {"hook": "Kai jumped the bridge", "post_caption": "Day one chaos 😭 #gta6"}}


def make(tmp_path):
    cfg = Config()
    cfg.post.folder = str(tmp_path / "POST")
    cfg.clips.output_dir = str(tmp_path / "clips")
    (tmp_path / "clips").mkdir()
    (tmp_path / "POST").mkdir()
    (tmp_path / "clips" / "twitch_kai_1.json").write_text(json.dumps(META), encoding="utf-8")
    clip = tmp_path / "POST" / "twitch_kai_1_vertical.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=180x320:rate=10",
                    "-t", "3", "-pix_fmt", "yuv420p", str(clip)], check=True)
    cfg.phone.key = "secret-key"
    return cfg, clip


def run(cfg, fn):
    async def go():
        server = PhoneServer(cfg, None)
        async with TestClient(TestServer(server.app())) as client:
            return await fn(client, server)
    return asyncio.run(go())


def test_key_required(tmp_path):
    cfg, _ = make(tmp_path)

    async def fn(c, s):
        assert (await c.get("/api/clips")).status == 403
        assert (await c.get("/api/clips", headers={"X-Clipper-Key": "wrong"})).status == 403
        assert (await c.get("/media/twitch_kai_1_vertical.mp4")).status == 403
        assert (await c.get("/")).status == 200          # the page itself loads, then asks for the QR code
    run(cfg, fn)


def test_list_with_captions(tmp_path):
    cfg, _ = make(tmp_path)

    async def fn(c, s):
        r = await c.get("/api/clips", headers={"X-Clipper-Key": "secret-key"})
        clips = (await r.json())["clips"]
        assert len(clips) == 1
        clip = clips[0]
        assert clip["streamer"] == "KaiCenat" and clip["source"] == "Twitch" and clip["hook"] == "Kai jumped the bridge"
        by = {p["key"]: p for p in clip["platforms"]}
        assert set(by) == {"tiktok", "youtube", "instagram"}
        assert "#fyp" in by["tiktok"]["caption"] and by["youtube"]["title"].endswith("#shorts")
        assert "k=secret-key" in clip["video"]
    run(cfg, fn)


def test_video_supports_seeking_and_download(tmp_path):
    cfg, clip = make(tmp_path)

    async def fn(c, s):
        r = await c.get("/media/twitch_kai_1_vertical.mp4?k=secret-key", headers={"Range": "bytes=0-99"})
        assert r.status == 206 and len(await r.read()) == 100
        r = await c.get("/media/twitch_kai_1_vertical.mp4?k=secret-key&download=1")
        assert r.status == 200 and "attachment" in r.headers["Content-Disposition"]
        r = await c.get("/thumb/twitch_kai_1_vertical.mp4?k=secret-key")
        assert r.status == 200 and (await r.read())[:2] == b"\xff\xd8"   # a JPEG
    run(cfg, fn)


def test_paths_outside_post_are_refused(tmp_path):
    cfg, _ = make(tmp_path)
    (tmp_path / "secret.mp4").write_bytes(b"x")

    async def fn(c, s):
        for bad in ("..%2Fsecret.mp4", "%2E%2E%2Fsecret.mp4", "..%5Csecret.mp4", "nothere.mp4", "notes.txt"):
            r = await c.get(f"/media/{bad}?k=secret-key")
            assert r.status == 404, bad
    run(cfg, fn)


def test_done_moves_clip_and_logs(tmp_path):
    cfg, clip = make(tmp_path)

    async def fn(c, s):
        r = await c.post("/api/clips/twitch_kai_1_vertical.mp4/done", headers={"X-Clipper-Key": "secret-key"},
                         json={"tiktok": "posted", "youtube": "nope"})
        assert r.status == 200
        r = await c.get("/api/clips", headers={"X-Clipper-Key": "secret-key"})
        assert (await r.json())["clips"] == []
    run(cfg, fn)
    done = tmp_path / "POST" / "posted"
    assert (done / clip.name).exists() and not clip.exists()
    log = json.loads((done / "log.jsonl").read_text().splitlines()[0])
    assert log == {**log, "tiktok": "posted", "youtube": "skipped", "instagram": "skipped"}


def test_manifest_and_page_carry_key_for_home_screen(tmp_path):
    cfg, _ = make(tmp_path)

    async def fn(c, s):
        page = await (await c.get("/?k=secret-key")).text()
        assert 'href="/manifest.webmanifest?k=secret-key"' in page
        m = json.loads(await (await c.get("/manifest.webmanifest?k=secret-key")).text())
        assert m["start_url"] == "/?k=secret-key" and m["display"] == "standalone"
        m = json.loads(await (await c.get("/manifest.webmanifest?k=guess")).text())
        assert m["start_url"] == "/"
        assert (await c.get("/icon-512.png")).status == 200
        svg = await (await c.get("/qr.svg")).read()             # test client connects from localhost
        assert svg.startswith(b"<?xml") or b"<svg" in svg[:200]
    run(cfg, fn)


def test_key_created_once_and_saved(tmp_path):
    conf = tmp_path / "config.toml"
    conf.write_text(open("config.example.toml", encoding="utf-8").read(), encoding="utf-8")
    cfg = Config()
    k1 = ensure_key(cfg, str(conf))
    assert len(k1) >= 20
    assert tomllib.loads(conf.read_text(encoding="utf-8"))["phone"]["key"] == k1
    assert ensure_key(cfg, str(conf)) == k1
