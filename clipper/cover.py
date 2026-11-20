"""A cover picture for each clip: the best moment of the clip with its headline on top.

Sites pick a frame for the cover by themselves, and in a browser that sometimes comes out as a
plain green square. Uploading this picture as the cover avoids that, and looks better anyway.

Covers are kept in clips/.covers/ and made again whenever the phone clip changes.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from .config import VerticalConfig
from .director import Plan
from .proc import BACKGROUND, NO_WINDOW
from .vertical import (WEBCAM_LAYOUTS, facecam_geometry, filter_graph, probe_duration, probe_size, resolve_layout,
                       with_headline, write_captions)

log = logging.getLogger(__name__)

COVERS = ".covers"


def cover_path(clips_dir: Path, phone_clip: Path) -> Path:
    return Path(clips_dir) / COVERS / f"{phone_clip.parent.parent.name}__{phone_clip.stem}.jpg"


def cover_time(meta: dict, length: float) -> float:
    """The moment chat exploded, which is the best picture of what the clip is about."""
    t = meta.get("explosion_offset")
    t = float(t) if isinstance(t, (int, float)) else length / 3
    return min(max(0.5, t), max(0.5, length - 0.5))


async def make_cover(phone_clip: Path, out: Path, meta: dict, cfg: VerticalConfig,
                     source: Path | None = None) -> Path | None:
    """Make (or reuse) the cover for a phone clip. With the caption-free original it's drawn clean:
    just the headline, no spoken words or reaction text half way through."""
    if out.exists() and out.stat().st_mtime >= phone_clip.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    cap = meta.get("captions") or {}
    tmp_out = out.with_name(out.stem + ".making.jpg")
    ok = False
    if source is not None and source.exists() and cap.get("hook") is not None:
        ok = await _from_source(source, tmp_out, cap, meta, cfg)
    if not ok:
        length = await asyncio.to_thread(probe_duration, phone_clip)
        ok = await _ffmpeg(["-ss", f"{cover_time(meta, length):.2f}", "-i", str(phone_clip),
                            "-frames:v", "1", "-q:v", "2", str(tmp_out)])
    if not ok or not tmp_out.exists():
        tmp_out.unlink(missing_ok=True)
        log.warning("couldn't make a cover for %s", phone_clip.name)
        return None
    tmp_out.replace(out)
    return out


async def _from_source(source: Path, out: Path, cap: dict, meta: dict, cfg: VerticalConfig) -> bool:
    length = await asyncio.to_thread(probe_duration, source)
    plan = Plan(hook=str(cap.get("hook", "")), mood=str(cap.get("mood", "hype")),
                crop_focus_x=float(cap.get("crop_focus_x", 0.5)), facecam=cap.get("facecam"))
    layout = cap.get("layout") or resolve_layout(cfg.layout, plan.facecam)
    geo = None
    if layout in WEBCAM_LAYOUTS:
        if not plan.facecam:
            layout = "blur"
        else:
            iw, ih = await asyncio.to_thread(probe_size, source)
            geo = facecam_geometry(plan.facecam, iw, ih, plan.crop_focus_x, full=layout == "facecam_full")
    with tempfile.TemporaryDirectory() as tmp:
        # The headline fades in over the first quarter second; a picture starts at time 0, so no fade.
        inputs, overlay = write_captions(Path(tmp), plan, [], length, layout, cfg, geo, fade=False)
        ass = Path(tmp) / "captions.ass"
        ass.write_text(ass.read_text(encoding="utf-8").replace("\\fad(250,0)", ""), encoding="utf-8")
        return await _ffmpeg(["-ss", f"{cover_time(meta, length):.2f}", "-i", str(source.resolve()), *inputs,
                              "-filter_complex", with_headline(filter_graph(layout, plan.crop_focus_x, False, geo), overlay),
                              "-map", "[v]", "-frames:v", "1", "-q:v", "2", str(out.resolve())], cwd=tmp)


async def _ffmpeg(args: list[str], cwd: str | None = None) -> bool:
    proc = await asyncio.create_subprocess_exec("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args,
                                                cwd=cwd, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE, **NO_WINDOW)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), 120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False
    if proc.returncode != 0:
        log.debug("cover: %s", err.decode(errors="replace")[-300:])
    return proc.returncode == 0
