"""YouTube live chat, read the same way the YouTube website does (no API key, no quota).

1. Open the chat popout page for the video and pull out the starting
   "continuation" token, switching from "Top chat" (filtered) to "Live chat"
   (every message, which is what we want to count).
2. Repeatedly ask YouTube's internal chat endpoint for new messages with that
   token. Each answer has the messages plus the next token and how long to wait.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

import aiohttp

from ..models import ChatMessage

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
    # Skip the EU cookie-consent page, which otherwise replaces the real page.
    "Cookie": "SOCS=CAI; CONSENT=YES+cb",
}
BASE = "https://www.youtube.com"


class ChatUnavailable(Exception):
    pass


# ---------------------------------------------------------------- parsing (pure)

def video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/live/|/shorts/)([\w-]{11})", url)
    return m.group(1) if m else (url if re.fullmatch(r"[\w-]{11}", url) else None)


def extract_json(html: str, name: str) -> dict | None:
    """Find `name = {...}` in a page and decode just that JSON object."""
    for m in re.finditer(re.escape(name) + r"\"?\]?\s*=\s*", html):
        start = html.find("{", m.end())
        if start == -1 or start - m.end() > 5:
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(html, start)
            return obj
        except json.JSONDecodeError:
            continue
    return None


def client_config(html: str) -> dict:
    key = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
    ver = (re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION"\s*:\s*"([^"]+)"', html)
           or re.search(r'"clientVersion"\s*:\s*"([^"]+)"', html))
    return {"key": key.group(1) if key else None, "version": ver.group(1) if ver else "2.20241101.00.00"}


def _first_continuation(conts: list) -> tuple[str | None, int | None]:
    for c in conts or []:
        for v in c.values():
            if isinstance(v, dict) and v.get("continuation"):
                return v["continuation"], v.get("timeoutMs")
    return None, None


def initial_continuation(data: dict) -> str:
    chat = (data.get("contents") or {}).get("liveChatRenderer")
    if not chat:
        raise ChatUnavailable("no live chat on this video (offline, a replay, or chat turned off)")
    # Prefer "Live chat" (all messages) over the default "Top chat".
    items = (((chat.get("header") or {}).get("liveChatHeaderRenderer") or {}).get("viewSelector") or {}) \
        .get("sortFilterSubMenuRenderer", {}).get("subMenuItems", [])
    for it in items:
        title = (it.get("title") or "").lower()
        cont = ((it.get("continuation") or {}).get("reloadContinuationData") or {}).get("continuation")
        if cont and "live" in title:
            return cont
    if items:
        cont = ((items[-1].get("continuation") or {}).get("reloadContinuationData") or {}).get("continuation")
        if cont:
            return cont
    cont, _ = _first_continuation(chat.get("continuations", []))
    if not cont:
        raise ChatUnavailable("couldn't find where the chat starts")
    return cont


def _text(runs: list) -> str:
    out = []
    for r in runs or []:
        if "text" in r:
            out.append(r["text"])
        elif "emoji" in r:
            e = r["emoji"]
            out.append((e.get("shortcuts") or [e.get("emojiId", "")])[0])
    return "".join(out)


def parse_actions(actions: list) -> list[ChatMessage]:
    msgs = []
    for a in actions or []:
        item = (a.get("addChatItemAction") or {}).get("item") or {}
        r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not r:
            continue
        user = (r.get("authorName") or {}).get("simpleText") or r.get("authorExternalChannelId") or "?"
        try:
            ts = int(r["timestampUsec"]) / 1e6
        except (KeyError, ValueError):
            ts = time.time()
        msgs.append(ChatMessage(user, _text((r.get("message") or {}).get("runs")), ts))
    return msgs


# ---------------------------------------------------------------- network

async def _bootstrap(session: aiohttp.ClientSession, url: str) -> tuple[dict, str]:
    vid = video_id(url)
    if not vid:  # e.g. a channel's /live page: find which video is live
        async with session.get(url, headers=HEADERS) as r:
            page = await r.text()
        m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', page)
        if not m:
            raise ChatUnavailable("couldn't find a live video at that link")
        vid = m.group(1)
    async with session.get(f"{BASE}/live_chat",
                           params={"is_popout": "1", "v": vid}, headers=HEADERS) as r:
        r.raise_for_status()
        html = await r.text()
    data = extract_json(html, "ytInitialData")
    if data is None:
        raise ChatUnavailable("YouTube returned a page without chat data")
    return client_config(html), initial_continuation(data)


async def _poll(session: aiohttp.ClientSession, cfg: dict, cont: str) -> dict:
    params = {"prettyPrint": "false"}
    if cfg["key"]:
        params["key"] = cfg["key"]
    body = {"context": {"client": {"clientName": "WEB", "clientVersion": cfg["version"], "hl": "en", "gl": "US"}},
            "continuation": cont}
    async with session.post(f"{BASE}/youtubei/v1/live_chat/get_live_chat", params=params, json=body, headers=HEADERS) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def youtube_chat(url: str, session: aiohttp.ClientSession) -> AsyncIterator[ChatMessage]:
    fails = 0
    while True:
        delay = 2
        try:
            cfg, cont = await _bootstrap(session, url)
            first = True
            while cont:
                data = await _poll(session, cfg, cont)
                lcc = (data.get("continuationContents") or {}).get("liveChatContinuation")
                if not lcc:
                    raise ChatUnavailable("chat ended")
                if first:
                    log.info("youtube chat connected: %s", url)
                    first = False
                for m in parse_actions(lcc.get("actions", [])):
                    yield m
                fails = 0  # only reset once messages actually flow
                cont, timeout_ms = _first_continuation(lcc.get("continuations", []))
                await asyncio.sleep(min(max((timeout_ms or 2000) / 1000, 0.5), 5))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            if session.closed:
                return  # clipping was stopped
            fails += 1
            delay = min(2 ** fails, 300)
            # Say it a few times, then only now and then, so the log stays readable.
            level = logging.WARNING if fails <= 3 or fails % 10 == 0 else logging.DEBUG
            log.log(level, "youtube chat unavailable for %s (%s), retrying in %ss", url, e, delay)
        await asyncio.sleep(delay)
