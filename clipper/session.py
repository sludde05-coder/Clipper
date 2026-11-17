"""One tracked channel: chat reader + spike detector + rolling recorder."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import aiohttp

from .chat import chat_source
from .config import Config
from .detector import Spike, SpikeDetector
from .models import ChatMessage, Stream
from .recorder import Recorder
from . import naming
from .naming import clip_path, commit_number
from .vertical import render_vertical

log = logging.getLogger(__name__)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:60]


class ChannelSession:
    def __init__(self, stream: Stream, cfg: Config, http: aiohttp.ClientSession, *,
                 source_cmd: list[str] | None = None, chat=None):
        self.stream = stream
        self.cfg = cfg
        self.http = http
        self.detector = SpikeDetector(cfg.detector)
        c = cfg.clips
        self.recorder = Recorder(
            stream.key, stream.url, Path(c.buffer_dir) / _safe(stream.key),
            segment_seconds=c.segment_seconds,
            keep_seconds=c.pre_roll + c.chat_delay + c.post_roll + 60,
            quality=c.quality, source_cmd=source_cmd)
        self._chat = chat
        self.recent: deque[ChatMessage] = deque(maxlen=2000)
        self.clips_saved = 0
        self._tasks: list[asyncio.Task] = []
        self._pending: set[asyncio.Task] = set()

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self.recorder.run(), name=f"rec-{self.stream.key}"),
                       asyncio.create_task(self._read_chat(), name=f"chat-{self.stream.key}"),
                       asyncio.create_task(self._watch(), name=f"watch-{self.stream.key}")]
        for t in self._tasks:
            t.add_done_callback(self._report_crash)

    def _report_crash(self, task: asyncio.Task) -> None:
        # A crashed background task would otherwise stop silently.
        if not task.cancelled() and task.exception() is not None:
            log.error("%s: %s stopped with an error: %r", self.stream.key, task.get_name(), task.exception())

    async def stop(self) -> None:
        # Let clips that are already waiting for their post-roll finish first.
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _read_chat(self) -> None:
        source = self._chat or chat_source(self.stream, self.http, self.cfg.creds)
        async for m in source:
            self.detector.add(m.user, m.ts)
            self.recent.append(m)

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(1)
            spike = self.detector.check()
            if spike and not self.recorder.live:
                log.warning("🔥 %s chat exploded (x%.1f) but no video is being recorded, so no clip. "
                            "See the recording messages for this channel.", self.stream.key, spike.ratio)
            if spike and self.recorder.live:
                log.info("🔥 %s chat exploded: %.1f msg/s vs %.1f normal (x%.1f, z=%.1f)",
                         self.stream.key, spike.rate, spike.baseline, spike.ratio, spike.zscore)
                t = asyncio.create_task(self._clip(spike))
                self._pending.add(t)
                t.add_done_callback(self._pending.discard)

    async def _clip(self, spike: Spike) -> None:
        c = self.cfg.clips
        start = spike.onset - c.pre_roll - c.chat_delay
        # Both ends are measured from the explosion, so every clip is exactly pre_roll + post_roll long.
        end = spike.onset + c.post_roll - c.chat_delay
        # Wait until the post-roll has been recorded and its segment closed.
        await asyncio.sleep(max(0.0, end - time.time()) + c.segment_seconds * 2 + 1)
        streamer = self.stream.display_name or self.stream.channel.split("#")[0]
        out, number = clip_path(c.output_dir, streamer, spike.onset)
        actual_start = await self.recorder.save_clip(start, end, out)
        if actual_start is None:
            return
        commit_number(naming.streamer_dir(out), number)
        details = naming.details_path(out)
        details.parent.mkdir(parents=True, exist_ok=True)
        self.clips_saved += 1
        window = [m for m in self.recent if spike.onset - 5 <= m.ts <= spike.detected_at + 10]
        timeline = [[round(m.ts - actual_start, 1), m.user, m.text]
                    for m in self.recent if actual_start <= m.ts <= end]
        meta = {
            "platform": self.stream.platform, "channel": self.stream.channel,
            "name": self.stream.display_name or self.stream.channel, "url": self.stream.url,
            "title": self.stream.title, "clip": out.name, "clip_number": number,
            "folder": naming.streamer_dir(out).name,
            "explosion_at": datetime.fromtimestamp(spike.onset).isoformat(timespec="seconds"),
            "clip_start": datetime.fromtimestamp(start).isoformat(timespec="seconds"),
            "clip_end": datetime.fromtimestamp(end).isoformat(timespec="seconds"),
            "chat_rate": round(spike.rate, 2), "normal_rate": round(spike.baseline, 2),
            "ratio": round(spike.ratio, 2) if spike.baseline else None, "zscore": round(spike.zscore, 1),
            "explosion_offset": round(spike.onset - actual_start, 1),
            "chat_sample": [f"{m.user}: {m.text}" for m in window[:40]],
            "chat_timeline": timeline[-400:],
        }
        details.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        with open(Path(c.output_dir) / "index.jsonl", "a") as f:
            f.write(json.dumps({k: v for k, v in meta.items() if k not in ("chat_sample", "chat_timeline")},
                               ensure_ascii=False) + "\n")
        log.info("🎬 clip saved: %s", out.name)
        folder = naming.streamer_dir(out)
        if not self.cfg.vertical.enabled:
            naming.move_into(out, folder / naming.ORIGINALS)
            return
        phone = await render_vertical(out, self.cfg.vertical, out=naming.phone_path(out),
                                      languages=self.cfg.discovery.languages, recent_dir=Path(c.output_dir),
                                      meta_path=details, aside_dir=folder / naming.OTHER_LANGUAGES)
        if not out.exists():
            return  # set aside (another language)
        if phone is None:
            kept = naming.move_into(out, folder / naming.NOT_CONVERTED)
            log.warning("kept the original in %s, since the phone version couldn't be made", kept.parent)
        elif c.keep_originals:
            naming.move_into(out, folder / naming.ORIGINALS)
        else:
            out.unlink(missing_ok=True)  # the phone version is the clip now
