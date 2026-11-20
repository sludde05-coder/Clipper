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

import uuid

import aiohttp

from ..config import Credentials
from ..models import ChatMessage

log = logging.getLogger(__name__)
UA = "Clipper/1.0 (+https://github.com/sludde05-coder/clipper)"

RETIRED_KEYS = {"32cbd69e4b950bf97679", "eb1d5f283081a78b932c"}   # Kick's old chat keys (refused now)
CURRENT_KEY, CURRENT_CLUSTER = "34bf7a0ff419a2a775b9", "us2"
_live_creds: tuple[str, str] | None = None   # the key and cluster Kick's own site uses right now

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


async def pusher_creds(session: aiohttp.ClientSession, creds: Credentials, fresh: bool = False) -> tuple[str, str]:
    """Kick's current chat (Pusher) key and cluster. Kick changes the key now and then (it did in Oct
    2026), so it's asked from the same address kick.com's own player uses; if that fails, the key in
    config.toml, unless that's one Kick has retired."""
    global _live_creds
    if _live_creds and not fresh:
        return _live_creds
    try:
        body = {"client": {"id": str(uuid.uuid4()), "type": "web"},
                "capabilities": {"accepted_providers": [{"provider": "pusher"}]}}
        async with session.post("https://web.kick.com/api/v1/realtime/connection", json=body,
                                headers={"Accept": "application/json", "User-Agent": UA},
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
        for c in (data.get("data") or {}).get("connections") or []:
            cr = c.get("credentials") or {}
            key, cluster = str(cr.get("app_key", "")), str(cr.get("cluster", ""))
            if c.get("provider") == "pusher" and re.fullmatch(r"[A-Za-z0-9]{8,64}", key) \
                    and re.fullmatch(r"[a-z0-9-]{1,32}", cluster):
                _live_creds = (key, cluster)
                return _live_creds
    except Exception as e:  # noqa: BLE001
        log.debug("couldn't ask Kick for its chat key (%s): using the built-in one", e)
    key = creds.kick_pusher_key if creds.kick_pusher_key and creds.kick_pusher_key not in RETIRED_KEYS else CURRENT_KEY
    return key, creds.kick_pusher_cluster or CURRENT_CLUSTER


class PusherRefused(Exception):
    pass


async def chatroom_id(slug: str, session: aiohttp.ClientSession) -> int:
    if slug in ROOMS:
        return ROOMS[slug]
    # kick.com's address for a channel uses - where the name has _ (MJ_ARIES -> mj-aries)
    async with session.get(f"https://kick.com/api/v2/channels/{slug.replace('_', '-')}",
                           headers={"User-Agent": UA, "Accept": "application/json"}) as r:
        if r.status in (401, 403, 429, 503):
            raise NeedsRoom(f"kick.com turned the lookup away ({r.status})")
        r.raise_for_status()
        try:
            data = await r.json(content_type=None)
            room = int(data["chatroom"]["id"])
        except (ValueError, KeyError, TypeError) as e:     # e.g. a "checking your browser" page instead of data
            raise NeedsRoom("kick.com didn't give the chat-room number") from e
    ROOMS[slug] = room
    return room


async def kick_chat(channel: str, session: aiohttp.ClientSession, creds: Credentials) -> AsyncIterator[ChatMessage]:
    slug, _, room = channel.partition("#")
    slug = slug.lower()
    backoff = 2
    while True:
        try:
            room_id = int(room) if room else await chatroom_id(slug, session)
            STATUS[slug] = "connecting"
            key, cluster = await pusher_creds(session, creds)
            url = f"wss://ws-{cluster}.pusher.com/app/{key}?protocol=7&client=js&version=8.4.0&flash=false"
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
                    elif name == "pusher:error":
                        err = ev.get("data") or {}
                        err = json.loads(err) if isinstance(err, str) else err
                        code = int(err.get("code") or 0)
                        raise PusherRefused(f"Kick's chat refused the connection ({code}: {err.get('message', '')})")
                    elif name == "pusher_internal:subscription_succeeded":
                        log.info("kick:%s chat is live", slug)
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
        except PusherRefused as e:
            if session.closed:
                return
            STATUS[slug] = f"error: {e}"
            log.warning("kick:%s %s; asking Kick for its current chat key and trying again in %ss", slug, e, backoff)
            await pusher_creds(session, creds, fresh=True)
        except Exception as e:  # noqa: BLE001
            if session.closed:
                return  # clipping was stopped
            STATUS[slug] = f"error: {e}"
            log.warning("kick:%s chat dropped (%s), retrying in %ss", slug, e, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 120)
