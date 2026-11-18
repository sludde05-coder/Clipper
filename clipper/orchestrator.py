from __future__ import annotations

import asyncio
import logging

import aiohttp

from .config import Config
from .discovery import Discovery
from .models import Stream
from .session import ChannelSession

log = logging.getLogger(__name__)


class Orchestrator:
    """Keeps one ChannelSession per tracked stream and swaps them as rankings change."""

    def __init__(self, cfg: Config, config_path: str | None = None, *, start_phone: bool = True,
                 log_status: bool = True):
        self.cfg = cfg
        self.config_path = config_path
        self.start_phone = start_phone
        self.log_status = log_status
        self.sessions: dict[str, ChannelSession] = {}
        self.last_top: list[Stream] = []
        self.refresh_now = asyncio.Event()   # set to look for streams again right away (e.g. after blocking one)

    async def drop(self, keys: list[str]) -> None:
        """Stop clipping these streams now (clips already in progress are finished)."""
        stopping = [self.sessions.pop(k) for k in keys if k in self.sessions]
        await asyncio.gather(*(s.stop() for s in stopping), return_exceptions=True)

    def status_rows(self) -> list[dict]:
        rows = []
        for key, s in self.sessions.items():
            rows.append({"key": key, "platform": s.stream.platform,
                         "name": s.stream.display_name or s.stream.channel, "url": s.stream.url,
                         "viewers": s.stream.viewers, "title": s.stream.title, "video": s.recorder.live,
                         "chat": round(s.detector.last_rate, 1), "normal": round(s.detector.last_baseline, 1),
                         "peak": round(s.detector.peak_ratio(), 1), "need": round(s.detector.required_ratio(), 1),
                         "clips": s.clips_saved})
        return rows

    async def stop_all(self) -> None:
        """Stop every channel; clips already waiting for their last seconds are finished first."""
        sessions, self.sessions = list(self.sessions.values()), {}
        await asyncio.gather(*(s.stop() for s in sessions), return_exceptions=True)

    async def _start_phone(self) -> None:
        if not self.cfg.phone.enabled or not self.start_phone:
            return
        try:
            from .phone import PhoneServer
            if not await PhoneServer(self.cfg, self.config_path).start():
                log.info("📱 Phone app is already running in another window (port %s)", self.cfg.phone.port)
        except Exception as e:  # noqa: BLE001 - never let the phone app stop the clipping
            log.warning("📱 Phone app couldn't start: %s", e)

    async def _sync(self, wanted: list[Stream], http: aiohttp.ClientSession) -> None:
        keys = {s.key for s in wanted}
        for key in [k for k in self.sessions if k not in keys]:
            log.info("⏹  no longer tracking %s", key)
            asyncio.create_task(self.sessions.pop(key).stop())
        for st in wanted:
            if st.key not in self.sessions:
                log.info("▶  tracking %s (%s viewers) %s", st.key, f"{st.viewers:,}", st.title[:60])
                sess = ChannelSession(st, self.cfg, http)
                sess.start()
                self.sessions[st.key] = sess

    def status(self) -> None:
        if not self.log_status:
            return
        if not self.sessions:
            log.info("not tracking anything yet")
            return
        need = self.cfg.detector.multiplier
        lines = [f"{'channel':32} {'video':6} {'chat/s':>7} {'normal':>7} {'peak 10m':>9} {'clips':>5}"]
        for key, s in self.sessions.items():
            peak = s.detector.peak_ratio()
            lines.append(f"{key:32} {'live' if s.recorder.live else '--':6} "
                         f"{s.detector.last_rate:7.1f} {s.detector.last_baseline:7.1f} "
                         f"{('x%.1f' % peak) if peak else '-':>9} {s.clips_saved:5}")
        lines.append(f"A clip is made when chat jumps to about x{need:g} its normal speed (less for busy chats, more for quiet ones) AND at least "
                     f"{self.cfg.detector.min_rate:g} messages/s.")
        lines.append("'video --' means nothing is being recorded.")
        log.info("status\n  %s", "\n  ".join(lines))

    async def run_discovery(self) -> None:
        await self._start_phone()
        async with aiohttp.ClientSession(trust_env=True) as http:
            disc = Discovery(self.cfg, http)
            status_every, since_status = 30, 0
            while True:
                try:
                    top = await disc.top_streams()
                    self.last_top = top
                    log.info("top %d for %r: %s", self.cfg.discovery.top_n, self.cfg.discovery.game,
                             ", ".join(f"{s.key}({s.viewers:,})" for s in top) or "none live")
                    await self._sync(top, http)
                except Exception:  # noqa: BLE001
                    log.exception("discovery round failed")
                waited = 0
                self.refresh_now.clear()
                while waited < self.cfg.discovery.refresh_seconds and not self.refresh_now.is_set():
                    try:
                        await asyncio.wait_for(self.refresh_now.wait(), 5)
                    except asyncio.TimeoutError:
                        pass
                    waited += 5
                    since_status += 5
                    if since_status >= status_every:
                        self.status()
                        since_status = 0

    async def run_fixed(self, streams: list[Stream]) -> None:
        await self._start_phone()
        async with aiohttp.ClientSession(trust_env=True) as http:
            await self._sync(streams, http)
            while True:
                await asyncio.sleep(30)
                self.status()
