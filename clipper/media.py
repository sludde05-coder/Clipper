"""Light versions of clips for watching on a phone: a small picture (thumb) and a small video (preview).

A phone clip is about 8 Mbit/s at 1080x1920: too heavy to scroll through over Wi-Fi or mobile data.
The preview is 540x960 at about 1 Mbit/s, so a feed of them plays smoothly. They're made once,
kept in clips/.thumbs and clips/.previews, and made again when the clip changes. ffmpeg runs one or
two at a time at low priority, so a phone opening a big library can't swamp the PC (or the recording).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .proc import BACKGROUND

log = logging.getLogger(__name__)

_thumb_slots: asyncio.Semaphore | None = None
_preview_slots: asyncio.Semaphore | None = None
_making: dict[Path, asyncio.Task] = {}


def _slots() -> tuple[asyncio.Semaphore, asyncio.Semaphore]:
    global _thumb_slots, _preview_slots
    if _thumb_slots is None:
        _thumb_slots, _preview_slots = asyncio.Semaphore(2), asyncio.Semaphore(1)
    return _thumb_slots, _preview_slots


def _fresh(out: Path, src: Path) -> bool:
    try:
        return out.exists() and out.stat().st_mtime >= src.stat().st_mtime and out.stat().st_size > 0
    except OSError:
        return False


def cache_name(clips_dir: Path, clip: Path, folder: str, ext: str) -> Path:
    return Path(clips_dir) / folder / f"{clip.parent.parent.name}__{clip.stem}{ext}"


async def _run(args: list[str], timeout: float) -> bool:
    proc = await asyncio.create_subprocess_exec("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args,
                                                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                                                **BACKGROUND)
    try:
        await asyncio.wait_for(proc.wait(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False
    except asyncio.CancelledError:
        proc.kill()
        raise
    return proc.returncode == 0


async def thumb(clips_dir: Path, clip: Path) -> Path | None:
    """A 270-px-wide picture from 1.5 s into the clip."""
    out = cache_name(clips_dir, clip, ".thumbs", ".jpg")
    if _fresh(out, clip):
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    async with _slots()[0]:
        if _fresh(out, clip):
            return out
        tmp = out.with_name(out.stem + ".making.jpg")
        ok = await _run(["-ss", "1.5", "-i", str(clip), "-frames:v", "1", "-vf", "scale=270:-2", "-q:v", "5", str(tmp)], 60)
        if ok and tmp.exists():
            tmp.replace(out)
            return out
        tmp.unlink(missing_ok=True)
    return out if out.exists() else None


async def preview(clips_dir: Path, clip: Path) -> Path | None:
    """The small video (540x960, ~1 Mbit/s), made now if needed."""
    out = cache_name(clips_dir, clip, ".previews", ".mp4")
    if _fresh(out, clip):
        return out
    task = _making.get(out)
    if task is None or task.done():
        task = asyncio.ensure_future(_make_preview(clip, out))
        _making[out] = task
    try:
        return await asyncio.shield(task)
    finally:
        if task.done():
            _making.pop(out, None)


def preview_ready(clips_dir: Path, clip: Path) -> Path | None:
    out = cache_name(clips_dir, clip, ".previews", ".mp4")
    return out if _fresh(out, clip) else None


async def _make_preview(clip: Path, out: Path) -> Path | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    async with _slots()[1]:
        if _fresh(out, clip):
            return out
        tmp = out.with_name(out.stem + ".making.mp4")
        ok = await _run(["-i", str(clip), "-vf", "scale=540:-2", "-c:v", "libx264", "-preset", "veryfast",
                         "-crf", "30", "-maxrate", "1200k", "-bufsize", "2400k", "-g", "60", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-movflags", "+faststart", str(tmp)], 600)
        if ok and tmp.exists():
            tmp.replace(out)
            return out
        tmp.unlink(missing_ok=True)
        log.debug("couldn't make a preview of %s", clip.name)
        return None


class Warmer:
    """Makes thumbs and previews of the newest clips ahead of time, one at a time, in the background."""

    def __init__(self, clips_dir: Path):
        self.clips_dir = Path(clips_dir)
        self.queue: list[Path] = []
        self.task: asyncio.Task | None = None

    def want(self, clips: list[Path], urgent: bool = False) -> None:
        """Queue clips; urgent ones (someone is looking at them right now) go first."""
        for c in reversed(clips) if urgent else clips:
            if preview_ready(self.clips_dir, c) and _fresh(cache_name(self.clips_dir, c, ".thumbs", ".jpg"), c):
                continue
            if urgent:
                if c in self.queue:
                    self.queue.remove(c)
                self.queue.insert(0, c)
            elif c not in self.queue:
                self.queue.append(c)
        if self.queue and (self.task is None or self.task.done()):
            self.task = asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        while self.queue:
            clip = self.queue.pop(0)
            if not clip.exists():
                continue
            try:
                await thumb(self.clips_dir, clip)
                await preview(self.clips_dir, clip)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.debug("warming %s: %s", clip.name, e)
