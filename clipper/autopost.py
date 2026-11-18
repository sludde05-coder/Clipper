"""Fills in the upload pages of TikTok, YouTube and Instagram in Clipper's own browser window,
so you only have to check the post and click Post yourself.

The window is Microsoft Edge (or Chrome) run by Playwright with a separate "Clipper" profile, so
you sign in to each site there once and stay signed in. Nothing is hidden: the sites can see it's
an automated browser, and the final Post/Publish/Share click is always yours.

Each step tries a few ways to find what it needs and gives up with a clear message instead of
hanging, so when a site changes its page you fall back to doing that step by hand.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
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

Status = Callable[[str], Awaitable[None] | None]


class NeedsSignIn(Exception):
    pass


class FillError(Exception):
    pass


class AutoPoster:
    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self._pw = None
        self._ctx = None
        self._pages: dict[str, object] = {}
        self._lock = asyncio.Lock()

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
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        headless = os.environ.get("CLIPPER_BROWSER_HEADLESS") == "1"  # tests only; normally you see the window
        opts = dict(user_data_dir=str(self.profile_dir), headless=headless, locale="en-US",
                    viewport=None, args=["--start-maximized"])
        override = os.environ.get("CLIPPER_BROWSER_PATH")
        attempts = ([{"executable_path": override}] if override else []) + \
                   ([{"channel": "msedge"}, {"channel": "chrome"}] if sys.platform == "win32" else
                    [{"channel": "chrome"}, {"channel": "msedge"}]) + [{}]
        last = None
        for extra in attempts:
            try:
                self._ctx = await self._pw.chromium.launch_persistent_context(**opts, **extra)
                self._ctx.on("close", lambda *_: self._closed())
                return self._ctx
            except Exception as e:  # noqa: BLE001
                last = e
        raise FillError(f"couldn't open Clipper's browser window ({last})")

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

    async def open_sign_in(self, platform: str) -> None:
        page = await self._page(platform)
        await page.goto(SIGN_IN_URL[platform])

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

    async def fill(self, platform: str, video: Path, captions: dict[str, str], status: Status) -> str:
        """Fill in one platform's upload page. Returns what's left for you to click."""
        async with self._lock:
            page = await self._page(platform)
            await _say(status, "Opening the upload page")
            await page.goto(UPLOAD_URL[platform], wait_until="domcontentloaded")
            if self._looks_signed_out(page.url):
                raise NeedsSignIn(platform)
            if platform == "tiktok":
                return await self._tiktok(page, video, captions, status)
            if platform == "youtube":
                return await self._youtube(page, video, captions, status)
            if platform == "instagram":
                return await self._instagram(page, video, captions, status)
            raise FillError(f"unknown platform {platform}")

    async def _tiktok(self, page, video, captions, status) -> str:
        await self._upload(page, video, status, "tiktok")
        await _say(status, "Writing the caption")
        box = await self._first(page, ['div[contenteditable="true"].public-DraftEditor-content',
                                       '[data-e2e="caption_container"] div[contenteditable="true"]',
                                       'div[contenteditable="true"]'], timeout=90)
        if box is None:
            raise FillError("the video is in, but the caption box didn't show up: paste the caption yourself")
        await self._replace_text(page, box, captions["caption"])
        return "Check it, wait for the upload to finish, then click Post"

    async def _youtube(self, page, video, captions, status) -> str:
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

    async def _instagram(self, page, video, captions, status) -> str:
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
        for _ in range(2):  # crop -> edit -> caption
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
        return "Check it, then click Share"


async def _say(status: Status, text: str) -> None:
    r = status(text)
    if asyncio.iscoroutine(r):
        await r
