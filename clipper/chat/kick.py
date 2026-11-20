"""Kick chat via Kick's Pusher WebSocket.

Reading a channel's chat needs its chat-room number. Kick's official API doesn't give it, and the
kick.com page that does is behind Cloudflare, which turns programs away. So Clipper asks once, and
otherwise uses the number you looked up in your own browser (the app's "Connect chat" button opens
the page and reads the number from what you paste). Numbers are kept in config.toml under
[kick] chatrooms, so it's a one-time step per streamer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

import aiohttp

from ..config import Credentials
from ..models import ChatMessage

log = logging.getLogger(__name__)
UA = "Clipper/1.0 (+https://github.com/sludde05-coder/clipper)"

ROOMS: dict[str, int] = {}        # slug -> chat-room number
STATUS: dict[str, str] = {}       # slug -> "" when chat is connected, "needs_room" when the number is missing


class NeedsRoom(Exception):
    pass


def load_rooms(entries: list[str]) -> None:
    for e in entries:
        slug, _, room = str(e).partition("#")
        if slug and room.strip().isdigit():
            ROOMS[slug.strip().lower()] = int(room)


def room_from_text(text: str) -> int | None:
    """The chat-room number from a pasted number, or from the whole channel page pasted as text."""
    text = (text or "").strip()
    if text.isdigit():
        return int(text)
    m = re.search(r'"chatroom"\s*:\s*\{[^{}]*?"id"\s*:\s*(\d+)', text) or \
        re.search(r'"chatroom_id"\s*:\s*(\d+)', text)
    return int(m.group(1)) if m else None


async def chatroom_id(slug: str, session: aiohttp.ClientSession) -> int:
    if slug in ROOMS:
        return ROOMS[slug]
    async with session.get(f"https://kick.com/api/v2/channels/{slug}",
                           headers={"User-Agent": UA, "Accept": "application/json"}) as r:
        if r.status in (401, 403, 429):
            raise NeedsRoom(f"kick.com turned the lookup away ({r.status})")
        r.raise_for_status()
        data = await r.json(content_type=None)
    room = int(data["chatroom"]["id"])
    ROOMS[slug] = room
    return room


async def kick_chat(channel: str, session: aiohttp.ClientSession, creds: Credentials) -> AsyncIterator[ChatMessage]:
    slug, _, room = channel.partition("#")
    slug = slug.lower()
    backoff = 2
    while True:
        try:
            room_id = int(room) if room else await chatroom_id(slug, session)
            url = (f"wss://ws-{creds.kick_pusher_cluster}.pusher.com/app/{creds.kick_pusher_key}"
                   "?protocol=7&client=js&version=8.4.0&flash=false")
            async with session.ws_connect(url, heartbeat=60) as ws:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    ev = json.loads(msg.data)
                    name = ev.get("event", "")
                    if name == "pusher:connection_established":
                        await ws.send_str(json.dumps({"event": "pusher:subscribe",
                                                      "data": {"auth": "", "channel": f"chatrooms.{room_id}.v2"}}))
                        log.info("kick:%s chat connected (room %s)", slug, room_id)
                        STATUS[slug] = ""
                        backoff = 2
                    elif name == "pusher:ping":
                        await ws.send_str(json.dumps({"event": "pusher:pong", "data": {}}))
                    elif name.endswith("ChatMessageEvent"):
                        data = json.loads(ev["data"]) if isinstance(ev.get("data"), str) else ev.get("data", {})
                        user = (data.get("sender") or {}).get("username", "?")
                        yield ChatMessage(user=user, text=data.get("content", ""), ts=time.time())
        except asyncio.CancelledError:
            raise
        except NeedsRoom as e:
            if session.closed:
                return
            if STATUS.get(slug) != "needs_room":
                log.warning("kick:%s chat isn't connected: %s. On the Clipping tab, press \"Connect chat\" on "
                            "%s's row (one time).", slug, e, slug)
            STATUS[slug] = "needs_room"
            await asyncio.sleep(5)           # picks the number up within seconds once you've given it
            continue
        except Exception as e:  # noqa: BLE001
            if session.closed:
                return  # clipping was stopped
            log.warning("kick:%s chat dropped (%s), retrying in %ss", slug, e, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 120)
