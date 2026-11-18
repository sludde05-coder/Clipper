"""Auto-fill against stand-in upload pages (tests/fake_sites) that copy how each site's page is
built. The real sites can change at any time; these check Clipper's side of the work."""
import asyncio
import functools
import glob
import http.server
import os
import subprocess
import threading
from pathlib import Path

import pytest

from clipper import autopost

SITES = Path(__file__).parent / "fake_sites"
CHROME = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
pytestmark = pytest.mark.skipif(not CHROME, reason="no browser available for this test")


@pytest.fixture()
def site(monkeypatch, tmp_path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITES))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setattr(autopost, "UPLOAD_URL", {k: f"{base}/{k}.html" for k in ("tiktok", "youtube", "instagram")})
    monkeypatch.setenv("CLIPPER_BROWSER_PATH", CHROME[-1])
    monkeypatch.setenv("CLIPPER_BROWSER_HEADLESS", "1")
    video = tmp_path / "KaiCenat_2026-11-19_21-34-12_1.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30",
                    "-t", "1", "-pix_fmt", "yuv420p", str(video)], check=True)
    yield video, tmp_path
    srv.shutdown()


def run(tmp_path, fn):
    async def go():
        ap = autopost.AutoPoster(tmp_path / "profile")
        try:
            return await fn(ap)
        finally:
            await ap.close()
    return asyncio.run(go())


def test_tiktok_fills_video_and_caption(site):
    video, tmp = site
    steps = []

    async def fn(ap):
        left = await ap.fill("tiktok", video, {"caption": "He really did that 😭\n🎥 KaiCenat on Twitch\n#gta6 #fyp"}, steps.append)
        page = ap._pages["tiktok"]
        return left, await page.evaluate("window.__file"), await page.inner_text("#cap")
    left, file, caption = run(tmp, fn)
    assert file == video.name
    assert caption.replace("\r", "").split("\n") == ["He really did that 😭", "🎥 KaiCenat on Twitch", "#gta6 #fyp"]
    assert "Post" in left and "Writing the caption" in steps


def test_youtube_fills_title_description_and_goes_to_publish(site):
    video, tmp = site

    async def fn(ap):
        left = await ap.fill("youtube", video, {"title": "Kai trusted the NPC | KaiCenat #shorts",
                                                "description": "Line one\n#shorts"}, lambda s: None)
        page = ap._pages["youtube"]
        return (left, await page.inner_text("#title-textarea #textbox"), await page.inner_text("#description-textarea #textbox"),
                await page.evaluate("[window.__kids, window.__steps, window.__vis]"))
    left, title, desc, (kids, steps, vis) = run(tmp, fn)
    assert title == "Kai trusted the NPC | KaiCenat #shorts" and desc.replace("\r", "").split("\n") == ["Line one", "#shorts"]
    assert (kids, steps, vis) == ("no", 3, "public")
    assert "Publish" in left


def test_instagram_goes_through_create_and_fills_caption(site):
    video, tmp = site

    async def fn(ap):
        left = await ap.fill("instagram", video, {"caption": "Day one chaos\n\n#reels"}, lambda s: None)
        page = ap._pages["instagram"]
        return left, await page.evaluate("[window.__file, window.__nexts]"), await page.inner_text("#cap")
    left, (file, nexts), caption = run(tmp, fn)
    assert file == video.name and nexts == 2
    assert caption.replace("\r", "").split("\n") == ["Day one chaos", "", "#reels"]
    assert "Share" in left


def test_signed_out_page_asks_to_sign_in(site, monkeypatch):
    video, tmp = site
    monkeypatch.setitem(autopost.UPLOAD_URL, "tiktok", autopost.UPLOAD_URL["tiktok"].replace("tiktok.html", "login/tiktok.html"))
    (SITES / "login").mkdir(exist_ok=True)
    (SITES / "login" / "tiktok.html").write_text("<!doctype html><p>Log in</p>", encoding="utf-8")

    async def fn(ap):
        with pytest.raises(autopost.NeedsSignIn):
            await ap.fill("tiktok", video, {"caption": "x"}, lambda s: None)
    try:
        run(tmp, fn)
    finally:
        (SITES / "login" / "tiktok.html").unlink()
        (SITES / "login").rmdir()


def test_missing_page_parts_give_a_clear_message(site, monkeypatch):
    video, tmp = site
    monkeypatch.setitem(autopost.UPLOAD_URL, "instagram", autopost.UPLOAD_URL["instagram"].replace("instagram.html", "tiktok.html"))
    monkeypatch.setattr(autopost.AutoPoster, "_first", _fast_first(autopost.AutoPoster._first))

    async def fn(ap):
        with pytest.raises(autopost.FillError, match="Create button"):
            await ap.fill("instagram", video, {"caption": "x"}, lambda s: None)
    run(tmp, fn)


def _fast_first(orig):
    async def first(page, selectors, timeout, state="visible"):
        return await orig(page, selectors, min(timeout, 2), state)
    return staticmethod(first)
