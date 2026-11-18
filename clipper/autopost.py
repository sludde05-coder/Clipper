"""Fills in the upload pages of TikTok, YouTube and Instagram in Clipper's own browser window,
so you only have to check the post and click Post yourself.

The window is Google Chrome, run by Playwright with its own profile called "Clipper", so you sign
in to each site there once and stay signed in. (Chrome doesn't allow programs to control your
normal Chrome profiles since version 136, so it can't be one you made in Chrome yourself.) Nothing is hidden: the sites can see it's
an automated browser, and the final Post/Publish/Share click is always yours.

Each step tries a few ways to find what it needs and gives up with a clear message instead of
hanging, so when a site changes its page you fall back to doing that step by hand.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

UPLOAD_URL = {
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
    "youtube": "https://www.youtube.com/upload",
    "instagram": "https://www.instagram.com/",
}
SIGN_IN_URL = {
    "tiktok": "https://www.tiktok.com/login",
    "youtube": "https://studio.youtube.com",
    "instagram": "https://www.instagram.com/accounts/login/",
}
# Button texts in English, plus Swedish in case a site shows the account's language.
NEXT = re.compile(r"^\s*(Next|Nästa)\s*$", re.I)
OK = re.compile(r"^\s*(OK|Okej)\s*$", re.I)
POST_ITEM = re.compile(r"^\s*(Post|Inlägg)\s*$", re.I)
EDIT_COVER = re.compile(r"^\s*(Edit cover|Redigera omslag|Ändra omslag)\s*$", re.I)
UPLOAD_COVER = re.compile(r"^\s*(Upload cover|Ladda upp omslag)\s*$", re.I)
CONFIRM_COVER = re.compile(r"^\s*(Confirm|Save|Done|Bekräfta|Spara|Klar)\s*$", re.I)
IG_COVER = re.compile(r"^\s*(Select from computer|Välj från datorn|Välj från dator)\s*$", re.I)
COVER_MISSED = "Cover: Clipper couldn't set it, so pick one yourself (the cover file is in clips/.covers)"

Status = Callable[[str], Awaitable[None] | None]


class NeedsSignIn(Exception):
    pass


class FillError(Exception):
    pass


class NotConfirmed(Exception):
    """Post was clicked, but the site didn't confirm it went up (so it might not have)."""


class AutoPoster:
    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self._pw = None
        self._ctx = None
        self._pages: dict[str, object] = {}
        self._lock = asyncio.Lock()
        self._signin_proc: subprocess.Popen | None = None

    # ------------------------------------------------------------ browser

    async def _context(self):
        if self._ctx is not None:
            try:
                _ = self._ctx.pages  # still open?
                return self._ctx
            except Exception:  # noqa: BLE001
                self._ctx = None
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise FillError("the auto-fill part isn't installed: run install.bat again") from e
        if self._pw is None:
            self._pw = await async_playwright().start()
        # Another Chrome with this profile open (e.g. the sign-in window) makes a new one hand over to it
        # and quit straight away: you'd see a blank page and auto-fill would fail. Close ours first.
        if profile_in_use(self.profile_dir):
            await self._close_sign_in_window()
        if profile_in_use(self.profile_dir):
            raise FillError("Chrome is still open with the Clipper profile (the sign-in window?). "
                            "Close every Chrome window titled Clipper, then press Fill in again")
        self._name_profile()
        headless = os.environ.get("CLIPPER_BROWSER_HEADLESS") == "1"  # tests only; normally you see the window
        opts = dict(user_data_dir=str(self.profile_dir), headless=headless, locale="en-US",
                    viewport=None,
                    # Software video decoding: with the graphics chip decoding, a site grabbing a frame
                    # for the cover could get an empty buffer, which shows up as a plain green cover.
                    args=["--start-maximized", "--disable-accelerated-video-decode"],
                    # Keep Chrome's security sandbox on (Playwright turns it off by default, which is
                    # what the "--no-sandbox" warning was about). Tests running as root can't use it.
                    chromium_sandbox=os.environ.get("CLIPPER_BROWSER_NO_SANDBOX") != "1")
        override = os.environ.get("CLIPPER_BROWSER_PATH")
        # Google Chrome, always. Edge only if Chrome isn't installed at all.
        if override:
            attempts = [{"executable_path": override}]
        elif find_chrome() is not None:
            attempts = [{"channel": "chrome"}]
        else:
            attempts = [{"channel": "chrome"}, {"channel": "msedge"}]
        last = None
        for extra in attempts:
            try:
                self._ctx = await self._pw.chromium.launch_persistent_context(**opts, **extra)
                self._ctx.on("close", lambda *_: self._closed())
                if extra.get("channel") == "msedge":
                    log.warning("Google Chrome isn't installed, so Clipper's browser window uses Microsoft Edge")
                return self._ctx
            except Exception as e:  # noqa: BLE001
                last = e
        if profile_in_use(self.profile_dir) or any(k in str(last) for k in ("ProcessSingleton", "in use", "already running")):
            raise FillError("Chrome is still open with the Clipper profile (the sign-in window?). "
                            "Close every Chrome window titled Clipper, then press Fill in again")
        first_line = str(last).strip().splitlines()[0][:200] if last else "unknown error"
        raise FillError(f"couldn't open Google Chrome for Clipper ({first_line})")

    def _name_profile(self) -> None:
        """Name the profile "Clipper", and stop Chrome from staying open in the background with it
        after its windows are closed (that would keep the profile busy)."""
        import json
        prefs = self.profile_dir / "Default" / "Preferences"
        if not prefs.exists():
            prefs.parent.mkdir(parents=True, exist_ok=True)
            prefs.write_text(json.dumps({"profile": {"name": "Clipper"}}), encoding="utf-8")
        state_file = self.profile_dir / "Local State"
        try:
            state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        except (OSError, ValueError):
            return
        if state.get("background_mode", {}).get("enabled") is not False:
            state.setdefault("background_mode", {})["enabled"] = False
            try:
                state_file.write_text(json.dumps(state), encoding="utf-8")
            except OSError:
                pass

    async def _close_sign_in_window(self) -> None:
        """Close the sign-in Chrome window Clipper opened, the normal way (so logins are saved)."""
        proc = self._signin_proc
        if proc is None or proc.poll() is not None:
            return
        log.info("closing the sign-in Chrome window so Clipper can use the profile")
        try:
            if sys.platform == "win32":
                from .proc import NO_WINDOW
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T"], capture_output=True, **NO_WINDOW)
            else:
                proc.terminate()
        except OSError:
            return
        for _ in range(30):  # up to 15 s for Chrome to save and let go of the profile
            if not profile_in_use(self.profile_dir):
                break
            await asyncio.sleep(0.5)
        self._signin_proc = None

    def _closed(self) -> None:
        self._ctx = None
        self._pages = {}

    async def _page(self, platform: str):
        ctx = await self._context()
        page = self._pages.get(platform)
        if page is None or page.is_closed():
            page = ctx.pages[0] if (len(ctx.pages) == 1 and ctx.pages[0].url in ("about:blank", "")) else await ctx.new_page()
            self._pages[platform] = page
        await page.bring_to_front()
        return page

    async def open_sign_in(self, platforms: list[str]) -> None:
        """Open the sign-in pages in a NORMAL Chrome window that uses the Clipper profile.

        Google refuses sign-ins in a browser that a program is controlling ("This browser or app
        may not be secure"), so signing in happens in plain Chrome. The login is saved in the
        Clipper profile, and the auto-fill window uses that same profile afterwards. Both can't
        have the profile open at once, so the automated window is closed first."""
        await self.close()
        chrome = find_chrome()
        if chrome is None:
            raise FillError("Google Chrome isn't installed. Get it from google.com/chrome")
        self._name_profile()
        self._signin_proc = subprocess.Popen([str(chrome), f"--user-data-dir={self.profile_dir}", "--no-first-run",
                                              "--no-default-browser-check", *[SIGN_IN_URL[p] for p in platforms]])

    async def close(self) -> None:
        try:
            if self._ctx is not None:
                await self._ctx.close()
            if self._pw is not None:
                await self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._ctx = self._pw = None

    # ------------------------------------------------------------ helpers

    @staticmethod
    async def _first(page, selectors: list[str], timeout: float, state: str = "visible"):
        """The first of several selectors that shows up within `timeout` seconds, or None."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            for sel in selectors:
                loc = page.locator(sel).first
                try:
                    if state == "attached" and await loc.count():
                        return loc
                    if state == "visible" and await loc.is_visible():
                        return loc
                except Exception:  # noqa: BLE001
                    continue
            await asyncio.sleep(0.5)
        return None

    @staticmethod
    async def _replace_text(page, box, text: str) -> None:
        """Clear a text box (plain or rich-text) and put `text` in it, emoji and all."""
        await box.click()
        await page.keyboard.press("Control+A" if sys.platform != "darwin" else "Meta+A")
        await page.keyboard.press("Backspace")
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line:
                await page.keyboard.insert_text(line)
            if i < len(lines) - 1:
                await page.keyboard.press("Shift+Enter")

    @staticmethod
    def _looks_signed_out(url: str) -> bool:
        return any(k in url for k in ("/login", "accounts/login", "ServiceLogin", "signin"))

    async def _upload(self, page, video: Path, status: Status, platform: str) -> None:
        await _say(status, "Putting the video in")
        file_input = await self._first(page, ['input[type="file"][accept*="video"]', 'input[type="file"]'],
                                        timeout=45, state="attached")
        if file_input is None:
            if self._looks_signed_out(page.url):
                raise NeedsSignIn(platform)
            raise FillError("couldn't find where to put the video on the page")
        await file_input.set_input_files(str(video))

    # ------------------------------------------------------------ the platforms

    async def fill(self, platform: str, video: Path, captions: dict[str, str], status: Status,
                   submit: bool = False, cover: Path | None = None) -> str:
        """Fill in one platform's upload page. Returns what's left for you to click, or, with
        submit=True, also clicks Post / Publish / Share and returns the site's confirmation."""
        async with self._lock:
            left = await self._fill(platform, video, captions, status, cover)
            if not submit:
                return left
            page = self._pages[platform]
            return await {"tiktok": self._post_tiktok, "youtube": self._post_youtube,
                          "instagram": self._post_instagram}[platform](page, status)

    async def _fill(self, platform: str, video: Path, captions: dict[str, str], status: Status,
                    cover: Path | None = None) -> str:
        page = await self._page(platform)
        await _say(status, "Opening the upload page")
        await page.goto(UPLOAD_URL[platform], wait_until="domcontentloaded")
        if self._looks_signed_out(page.url):
            raise NeedsSignIn(platform)
        if platform == "tiktok":
            return await self._tiktok(page, video, captions, status, cover)
        if platform == "youtube":
            return await self._youtube(page, video, captions, status, cover)
        if platform == "instagram":
            return await self._instagram(page, video, captions, status, cover)
        raise FillError(f"unknown platform {platform}")

    async def _tiktok(self, page, video, captions, status, cover=None) -> str:
        await self._upload(page, video, status, "tiktok")
        await _say(status, "Writing the caption")
        box = await self._first(page, ['div[contenteditable="true"].public-DraftEditor-content',
                                       '[data-e2e="caption_container"] div[contenteditable="true"]',
                                       'div[contenteditable="true"]'], timeout=90)
        if box is None:
            raise FillError("the video is in, but the caption box didn't show up: paste the caption yourself")
        await self._replace_text(page, box, captions["caption"])
        left = "Check it, wait for the upload to finish, then click Post"
        if cover is not None and not await self._cover_tiktok(page, cover, status):
            left = f"{left}. {COVER_MISSED}"
        return left

    # ------------------------------------------------------------ covers

    async def _cover_tiktok(self, page, cover: Path, status) -> bool:
        """Edit cover -> Upload cover -> the picture -> Confirm. False if any step isn't there."""
        await _say(status, "Setting the cover")
        edit = await _wait_enabled(page, [page.get_by_role("button", name=EDIT_COVER), page.get_by_text(EDIT_COVER)], 60)
        if edit is None:
            log.info("TikTok: no Edit cover button, so the cover wasn't set")
            return False
        try:
            await edit.click()
            tab = await _wait_enabled(page, [page.get_by_role("tab", name=UPLOAD_COVER),
                                             page.get_by_role("button", name=UPLOAD_COVER), page.get_by_text(UPLOAD_COVER)], 10)
            if tab is not None:
                await tab.click()
            if not await self._give_picture(page, cover, ['[role="dialog"] input[type="file"][accept*="image"]',
                                                          'input[type="file"][accept*="image"]']):
                raise FillError("no place to upload the picture")
            ok = await _wait_enabled(page, [page.locator('[role="dialog"]').get_by_role("button", name=CONFIRM_COVER),
                                            page.get_by_role("button", name=CONFIRM_COVER)], 30)
            if ok is None:
                raise FillError("no Confirm button")
            await ok.click()
            return True
        except Exception as e:  # noqa: BLE001
            log.info("TikTok: couldn't set the cover (%s)", e)
            try:
                await page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            return False

    async def _cover_instagram(self, page, cover: Path, status) -> bool:
        """On the Edit step: Cover photo -> Select from computer -> the picture."""
        await _say(status, "Setting the cover")
        btn = await _wait_enabled(page, [page.get_by_role("button", name=IG_COVER), page.get_by_text(IG_COVER)], 8)
        try:
            if btn is not None:
                async with page.expect_file_chooser(timeout=8000) as chooser:
                    await btn.click()
                await (await chooser.value).set_files(str(cover))
                await asyncio.sleep(1.5)
                return True
            return await self._give_picture(page, cover, ['[role="dialog"] input[type="file"][accept*="image"]'])
        except Exception as e:  # noqa: BLE001
            log.info("Instagram: couldn't set the cover (%s)", e)
            return False

    async def _cover_youtube(self, page, cover: Path, status) -> bool:
        """YouTube lets some channels pick a thumbnail for Shorts on a computer: use it if it's there."""
        await _say(status, "Setting the thumbnail")
        try:
            return await self._give_picture(page, cover, ['input#file-loader[accept*="image"]',
                                                          'ytcp-thumbnail-uploader input[type="file"]',
                                                          'ytcp-thumbnails-compact-editor-uploader input[type="file"]'],
                                            timeout=5)
        except Exception as e:  # noqa: BLE001
            log.info("YouTube: couldn't set the thumbnail (%s)", e)
            return False

    async def _give_picture(self, page, cover: Path, selectors: list[str], timeout: float = 15) -> bool:
        box = await self._first(page, selectors, timeout=timeout, state="attached")
        if box is None:
            return False
        await box.set_input_files(str(cover))
        await asyncio.sleep(1.5)
        return True

    async def _youtube(self, page, video, captions, status, cover=None) -> str:
        if self._looks_signed_out(page.url) or "accounts.google" in page.url:
            raise NeedsSignIn("youtube")
        await self._upload(page, video, status, "youtube")
        await _say(status, "Writing the title and description")
        title = await self._first(page, ["#title-textarea #textbox", "ytcp-social-suggestions-textbox#title-textarea #textbox"],
                                  timeout=90)
        if title is None:
            raise FillError("the video is in, but the title box didn't show up: paste the title yourself")
        await self._replace_text(page, title, captions["title"])
        desc = await self._first(page, ["#description-textarea #textbox"], timeout=10)
        if desc is not None:
            await self._replace_text(page, desc, captions["description"])
        if cover is not None:
            await self._cover_youtube(page, cover, status)
        not_for_kids = await self._first(page, ['tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
                                                'tp-yt-paper-radio-button[name="NOT_MADE_FOR_KIDS"]'], timeout=10)
        if not_for_kids is not None:
            await not_for_kids.click()
        await _say(status, "Going to the last step")
        for _ in range(3):
            nxt = await self._first(page, ["#next-button:not([disabled])"], timeout=15)
            if nxt is None:
                return "Click Next until the last step, choose Public, then click Publish"
            await nxt.click()
            await asyncio.sleep(1.2)
        public = await self._first(page, ['tp-yt-paper-radio-button[name="PUBLIC"]'], timeout=15)
        if public is not None:
            await public.click()
            return "Check it, then click Publish"
        return "Choose Public, then click Publish"

    # ------------------------------------------------------------ clicking Post

    async def _post_tiktok(self, page, status) -> str:
        await _say(status, "Waiting for the upload to finish")
        btn = await _wait_enabled(page, ['button[data-e2e="post_video_button"]',
                                         page.get_by_role("button", name=re.compile(r"^\s*(Post|Publicera|Lägg upp)\s*$", re.I))],
                                  UPLOAD_WAIT)
        if btn is None:
            raise FillError("the Post button never became clickable (upload not finished?): check TikTok and post by hand")
        await _say(status, "Posting")
        await btn.click()
        try:  # "Continue to post?" after TikTok's content check
            await page.get_by_role("button", name=re.compile(r"^\s*(Post now|Publicera nu)\s*$", re.I)).first.click(timeout=6000)
        except Exception:  # noqa: BLE001
            pass
        await _say(status, "Waiting for TikTok to confirm")
        if await _wait_for_any(page, [re.compile(r"(your video (has been|is being) (uploaded|posted)|video (posted|published)|"
                                                 r"manage (your )?posts|uploaded successfully)", re.I)],
                               url_parts=("/tiktokstudio/content", "/manage")):
            return "Posted on TikTok"
        raise NotConfirmed("Clicked Post, but TikTok didn't confirm it")

    async def _post_youtube(self, page, status) -> str:
        await _say(status, "Waiting for YouTube's checks")
        btn = await _wait_enabled(page, ["#done-button"], UPLOAD_WAIT)
        if btn is None:
            raise FillError("the Publish button never became clickable: check YouTube Studio and publish by hand")
        await _say(status, "Publishing")
        await btn.click()
        await _say(status, "Waiting for YouTube to confirm")
        if await _wait_for_any(page, ["ytcp-video-share-dialog", "ytcp-uploads-still-processing-dialog",
                                      re.compile(r"(video published|video processing|still processing)", re.I)]):
            try:
                await page.locator("#close-button").first.click(timeout=3000)
            except Exception:  # noqa: BLE001
                pass
            return "Published on YouTube"
        raise NotConfirmed("Clicked Publish, but YouTube didn't confirm it")

    async def _post_instagram(self, page, status) -> str:
        await _say(status, "Sharing")
        share = page.get_by_role("button", name=re.compile(r"^\s*(Share|Dela)\s*$", re.I))
        btn = await _wait_enabled(page, [share], 60)
        if btn is None:
            raise FillError("couldn't find the Share button: check Instagram and share by hand")
        await btn.click()
        await _say(status, "Waiting for Instagram to confirm (uploading)")
        if await _wait_for_any(page, [re.compile(r"((reel|post) (has been|was) shared|your reel has been shared|"
                                                 r"har delats)", re.I)], timeout=UPLOAD_WAIT):
            return "Shared on Instagram"
        raise NotConfirmed("Clicked Share, but Instagram didn't confirm it")

    async def _instagram(self, page, video, captions, status, cover=None) -> str:
        await _say(status, "Opening a new post")
        create = await self._first(page, ['svg[aria-label="New post"]', 'svg[aria-label="Create"]',
                                          'svg[aria-label="Nytt inlägg"]', 'svg[aria-label="Skapa"]'], timeout=25)
        if create is None:
            if self._looks_signed_out(page.url) or await page.locator('input[name="username"]').count():
                raise NeedsSignIn("instagram")
            raise FillError("couldn't find the Create button: click + Create yourself, then drag the clip in")
        await create.click()
        post_item = await self._first(page, ['svg[aria-label="Post"]', 'svg[aria-label="Inlägg"]'], timeout=4)
        if post_item is not None:
            await post_item.click()
        await self._upload(page, video, status, "instagram")
        ok = page.get_by_role("button", name=OK)
        try:
            await ok.first.click(timeout=4000)  # "Video posts are now shared as reels"
        except Exception:  # noqa: BLE001
            pass
        cover_set = cover is None
        for step in range(2):  # crop -> edit -> caption
            if step == 1 and cover is not None:   # the Edit step is where the cover photo is chosen
                cover_set = await self._cover_instagram(page, cover, status)
            nxt = page.get_by_role("button", name=NEXT)
            try:
                await nxt.first.click(timeout=30000)
            except Exception as e:  # noqa: BLE001
                raise FillError("the video is in, but the Next button didn't show up: click Next yourself") from e
            await asyncio.sleep(1.5)
        await _say(status, "Writing the caption")
        box = await self._first(page, ['div[role="dialog"] div[contenteditable="true"]',
                                       'div[aria-label^="Write a caption"]', 'textarea[aria-label^="Write a caption"]'],
                                timeout=20)
        if box is None:
            raise FillError("the video is in, but the caption box didn't show up: paste the caption yourself")
        await self._replace_text(page, box, captions["caption"])
        return "Check it, then click Share" + ("" if cover_set else f". {COVER_MISSED}")


def profile_in_use(profile_dir: Path) -> bool:
    """Is a Chrome running with this profile right now?"""
    if sys.platform == "win32":
        lock = profile_dir / "lockfile"   # Chrome keeps this open (and undeletable) while it runs
        if not lock.exists():
            return False
        try:
            lock.unlink()                  # left over from a crash: harmless to remove
            return False
        except PermissionError:
            return True
        except OSError:
            return False
    lock = profile_dir / "SingletonLock"   # a link to "<computer>-<process id>"
    try:
        target = os.readlink(lock)
    except OSError:
        return False
    try:
        os.kill(int(target.rsplit("-", 1)[1]), 0)
        return True
    except (ValueError, IndexError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def find_chrome() -> Path | None:
    """Where Google Chrome is installed on this computer."""
    candidates = []
    if sys.platform == "win32":
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        import shutil
        candidates += [Path(p) for p in (shutil.which("google-chrome"), shutil.which("google-chrome-stable"),
                                         shutil.which("chromium")) if p]
    return next((c for c in candidates if c.exists()), None)


UPLOAD_WAIT = 15 * 60    # how long to wait for an upload to finish before Post can be clicked
CONFIRM_WAIT = 4 * 60    # how long to wait for the site to say the post went up


async def _wait_enabled(page, selectors: list, timeout: float):
    """The first selector (CSS string or a ready locator) that is visible and clickable."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for sel in selectors:
            loc = (page.locator(sel) if isinstance(sel, str) else sel).first
            try:
                if await loc.is_visible() and await loc.is_enabled() and \
                        (await loc.get_attribute("aria-disabled")) != "true" and \
                        (await loc.get_attribute("data-disabled")) != "true":
                    return loc
            except Exception:  # noqa: BLE001
                continue
        await asyncio.sleep(1)
    return None


async def _wait_for_any(page, patterns: list, url_parts: tuple = (), timeout: float | None = None) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (CONFIRM_WAIT if timeout is None else timeout)
    while loop.time() < deadline:
        if any(u in page.url for u in url_parts):
            return True
        for pat in patterns:
            loc = page.locator(pat) if isinstance(pat, str) else page.get_by_text(pat)
            try:
                if await loc.first.is_visible():
                    return True
            except Exception:  # noqa: BLE001
                continue
        await asyncio.sleep(1)
    return False


async def _say(status: Status, text: str) -> None:
    r = status(text)
    if asyncio.iscoroutine(r):
        await r
