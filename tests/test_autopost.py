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
    monkeypatch.setenv("CLIPPER_BROWSER_NO_SANDBOX", "1")   # the test machine runs as root
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
        return left, await page.evaluate("[window.__file, window.__nexts, window.__shape]"), await page.inner_text("#cap")
    left, (file, nexts, shape), caption = run(tmp, fn)
    assert file == video.name and nexts == 2
    assert shape == "original"                      # full 9:16, not Instagram's default square
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


def test_sign_in_opens_plain_chrome_with_the_clipper_profile(tmp_path, monkeypatch):
    """Google blocks sign-in in automated browsers, so sign-in uses plain Chrome + the same profile."""
    launched = []
    fake_chrome = tmp_path / "chrome.exe"
    fake_chrome.write_text("")
    monkeypatch.setattr(autopost, "find_chrome", lambda: fake_chrome)
    monkeypatch.setattr(autopost.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))
    ap = autopost.AutoPoster(tmp_path / "chrome-profile")
    closed = []

    async def fake_close():
        closed.append(True)
    ap.close = fake_close
    asyncio.run(ap.open_sign_in(["tiktok", "youtube", "instagram"]))
    cmd = launched[0]
    assert closed and cmd[0] == str(fake_chrome)
    assert f"--user-data-dir={tmp_path / 'chrome-profile'}" in cmd
    assert not any("remote-debugging" in a or "enable-automation" in a for a in cmd)   # a normal Chrome
    assert [a for a in cmd if a.startswith("https://")] == [autopost.SIGN_IN_URL[k] for k in ("tiktok", "youtube", "instagram")]
    assert '"Clipper"' in (tmp_path / "chrome-profile" / "Default" / "Preferences").read_text(encoding="utf-8")


def test_profile_in_use_gives_a_clear_message(tmp_path, monkeypatch):
    class FakeChromium:
        async def launch_persistent_context(self, **kw):
            raise RuntimeError("Failed to create a ProcessSingleton for your profile directory")

    class FakePW:
        chromium = FakeChromium()

    ap = autopost.AutoPoster(tmp_path / "chrome-profile")
    ap._pw = FakePW()
    with pytest.raises(autopost.FillError, match="still open with the Clipper profile"):
        asyncio.run(ap._context())


def _start_chrome(profile, url="about:blank"):
    """A real Chrome holding the profile, like the sign-in window does."""
    proc = subprocess.Popen([CHROME[-1], "--headless=new", "--no-sandbox", f"--user-data-dir={profile}",
                             "--no-first-run", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import time
    for _ in range(40):
        if autopost.profile_in_use(profile):
            return proc
        time.sleep(0.25)
    proc.kill()
    raise AssertionError("test Chrome didn't start")


def test_closes_its_own_sign_in_window_then_fills_in(site):
    video, tmp = site
    profile = tmp / "profile"

    async def fn(ap):
        ap._signin_proc = _start_chrome(profile)
        assert autopost.profile_in_use(profile)
        await ap.fill("tiktok", video, {"caption": "hi"}, lambda s: None)
        return await ap._pages["tiktok"].inner_text("#cap"), ap._signin_proc
    caption, proc = run(tmp, fn)
    assert caption == "hi" and proc is None


def test_profile_open_elsewhere_gives_a_short_clear_message(site):
    video, tmp = site
    profile = tmp / "profile"
    other = _start_chrome(profile)          # not opened by Clipper, so it won't close it
    try:
        async def fn(ap):
            with pytest.raises(autopost.FillError) as e:
                await ap.fill("tiktok", video, {"caption": "hi"}, lambda s: None)
            return str(e.value)
        msg = run(tmp, fn)
        assert "still open with the Clipper profile" in msg and len(msg) < 200
    finally:
        other.kill()
        other.wait()


def test_background_mode_is_switched_off_for_the_profile(tmp_path):
    import json
    ap = autopost.AutoPoster(tmp_path / "p")
    ap._name_profile()
    assert json.loads((tmp_path / "p" / "Local State").read_text(encoding="utf-8"))["background_mode"]["enabled"] is False


@pytest.mark.parametrize("platform,caps,expect", [
    ("tiktok", {"caption": "x"}, "Posted on TikTok"),
    ("youtube", {"title": "t #shorts", "description": "d"}, "Published on YouTube"),
    ("instagram", {"caption": "x"}, "Shared on Instagram"),
])
def test_click_post_for_me(site, platform, caps, expect):
    video, tmp = site
    steps = []

    async def fn(ap):
        msg = await ap.fill(platform, video, caps, steps.append, submit=True)
        return msg, await ap._pages[platform].evaluate("window.__posted")
    msg, posted = run(tmp, fn)
    assert msg == expect and posted is True
    assert any("confirm" in s for s in steps)


def test_post_clicked_but_not_confirmed(site, monkeypatch):
    video, tmp = site
    monkeypatch.setitem(autopost.UPLOAD_URL, "tiktok", autopost.UPLOAD_URL["tiktok"] + "?silent=1")
    monkeypatch.setattr(autopost, "CONFIRM_WAIT", 3)

    async def fn(ap):
        with pytest.raises(autopost.NotConfirmed):
            await ap.fill("tiktok", video, {"caption": "x"}, lambda s: None, submit=True)
        return await ap._pages["tiktok"].evaluate("window.__posted")
    assert run(tmp, fn) is True          # it did click, and says it couldn't confirm


@pytest.mark.parametrize("platform", ["tiktok", "instagram"])
def test_cover_picture_is_set(site, platform):
    video, tmp = site
    cover = tmp / "cover.jpg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:size=180x320", "-frames:v", "1",
                    str(cover)], check=True)
    steps = []

    async def fn(ap):
        left = await ap.fill(platform, video, {"caption": "x"}, steps.append, cover=cover)
        return left, await ap._pages[platform].evaluate("window.__cover")
    left, got = run(tmp, fn)
    assert got == "cover.jpg" and "Setting the cover" in steps
    assert "Cover:" not in left                      # no "set it yourself" note


def test_chrome_decodes_video_in_software(site):
    """A green cover comes from a frame grabbed out of an empty hardware-decoder buffer."""
    video, tmp = site

    async def fn(ap):
        page = await ap._page("tiktok")
        await page.goto("chrome://version")
        return await page.inner_text("body")
    assert "--disable-accelerated-video-decode" in run(tmp, fn)


def test_instagram_is_not_shared_cut_to_a_square(site, monkeypatch):
    """If the Original shape can't be chosen, Clipper won't click Share for you."""
    video, tmp = site
    monkeypatch.setattr(autopost, "IG_CROP", ['svg[aria-label="Something else"]'])
    monkeypatch.setattr(autopost.AutoPoster, "_first", _fast_first(autopost.AutoPoster._first))

    async def fn(ap):
        left = await ap.fill("instagram", video, {"caption": "x"}, lambda s: None)
        assert "square" in left and "Original" in left
        with pytest.raises(autopost.FillError, match="square"):
            await ap.fill("instagram", video, {"caption": "x"}, lambda s: None, submit=True)
        return await ap._pages["instagram"].evaluate("window.__posted")
    assert run(tmp, fn) is None


def test_youtube_publishes_anyway_when_checks_are_not_done(site, monkeypatch):
    video, tmp = site
    monkeypatch.setitem(autopost.UPLOAD_URL, "youtube", autopost.UPLOAD_URL["youtube"] + "?checks=1")
    steps = []

    async def fn(ap):
        msg = await ap.fill("youtube", video, {"title": "t #shorts", "description": "d"}, steps.append, submit=True)
        return msg, await ap._pages["youtube"].evaluate("[window.__anyway, window.__posted]")
    msg, (anyway, posted) = run(tmp, fn)
    assert msg == "Published on YouTube" and anyway is True and posted is True
    assert any("anyway" in s for s in steps)
