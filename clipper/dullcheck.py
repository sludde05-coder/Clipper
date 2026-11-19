"""Finds finished clips where nothing really happens, so they can be trashed.

Two looks at every clip:
  1. The video itself (no AI): how much of it is a frozen or black picture.
  2. The AI: frames from across the whole clip, what the streamer says and how chat reacted, judged
     against "would anyone stop scrolling for this?"

The verdict is kept in the clip's details ("dull_check"), so a second scan only looks at new clips.
Nothing is deleted here: the app lists the verdicts and you move the ones you agree with to Deleted
clips (from where they can still be restored).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path

from .director import _ask, _extract_frames
from .editors import _image, chat_curve
from .proc import NO_WINDOW
from .vertical import probe_duration

log = logging.getLogger(__name__)

FRAMES = 8
TRASH_SCORE = 4          # 0-10: at or below this, the AI calls it dull

SCHEMA = {
    "type": "object",
    "properties": {
        "what_happens": {"type": "string"},
        "score": {"type": "integer"},
        "verdict": {"type": "string", "enum": ["keep", "trash"]},
        "why": {"type": "string"},
    },
    "required": ["what_happens", "score", "verdict", "why"],
    "additionalProperties": False,
}

PROMPT = """You are cleaning up a library of short vertical clips cut automatically from GTA 6 livestreams. Each clip was
cut because the stream's chat suddenly got busy, but a busy chat doesn't always mean something happened on stream:
chat also spikes for raids, subs and donations, giveaways, ads, a streamer saying "spam W", or an inside joke.

Decide if anything actually happens in THIS clip that a stranger scrolling TikTok would stop for.

Streamer: {name} ({platform}). Stream title: {title}
Headline on the clip: {hook}
Clip length: {length:.0f}s. Chat got {ratio} its normal speed.
Video check (no AI): {video}

What the streamer says (speech-to-text, may be empty):
{transcript}

Chat across the clip (messages per 2 seconds, most repeated messages):
{chat}

The images are frames spread across the whole finished clip, in order.

KEEP when there is a clear moment: a crash, chase, fight, fail, stunt, a funny or shocking line or reaction, a
surprise, something impressive, a genuinely funny conversation, a big reveal about the game.
TRASH when nothing really happens: just walking or driving around, menus, a map, loading or pause screens,
character creator, a black/frozen/"be right back" screen, the streamer away or talking about nothing in
particular, reading donations or ads, or chat clearly reacting to something not in the clip (a raid, a sub train).
Be thorough and honest: look at every frame and the words. When it's a close call, keep it.

Answer with: what_happens (one short sentence about what actually happens), score (0 = nothing at all happens,
10 = a must-post moment), verdict ("trash" if nothing really happens, otherwise "keep"), why (one short sentence a
person can check against the clip)."""


def video_check(clip: Path, length: float) -> dict:
    """Seconds of frozen and of black picture in the clip (ffmpeg's freezedetect / blackdetect)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(clip), "-an", "-vf",
                        "scale=240:-2,freezedetect=n=0.004:d=2,blackdetect=d=1:pix_th=0.12", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300, **NO_WINDOW)
    err = r.stderr or ""
    frozen = sum(float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", err))
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)]
    if len(starts) > len(ends):                       # still frozen when the clip ends
        frozen += max(0.0, length - starts[-1])
    black = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", err))
    return {"frozen": round(min(frozen, length), 1), "black": round(min(black, length), 1), "length": round(length, 1)}


def _describe(v: dict) -> str:
    if not v.get("length"):
        return "unknown"
    return (f"{v['frozen']:.0f}s of {v['length']:.0f}s is a frozen picture, "
            f"{v['black']:.0f}s is black")


async def check(clip: Path, meta: dict, model: str) -> dict:
    """The verdict for one phone clip: {"verdict": keep|trash|unsure, "score", "why", "what_happens", "video"}."""
    length = await asyncio.to_thread(probe_duration, clip)
    try:
        video = await asyncio.to_thread(video_check, clip, length)
    except (OSError, subprocess.SubprocessError):
        video = {"frozen": 0.0, "black": 0.0, "length": round(length, 1)}
    result = {"video": video, "at": datetime.now().isoformat(timespec="seconds"), "model": model}
    dead = (video["frozen"] + video["black"]) / max(length, 1)
    if dead >= 0.7:
        return {**result, "verdict": "trash", "score": 0, "by": "video",
                "what_happens": "The picture is frozen or black most of the time.",
                "why": f"{_describe(video)}."}
    cap = meta.get("captions") or {}
    words = cap.get("words") or []
    transcript = (" ".join(w[2] for w in words) if words else cap.get("transcript", "")) or "(no speech detected)"
    times = [round(min(length - 0.3, max(0.3, length * (i + 0.5) / FRAMES)), 1) for i in range(FRAMES)]
    frames = await asyncio.to_thread(_extract_frames, clip, times, 432)
    content: list[dict] = []
    for t, b64 in frames:
        _image(content, t, b64, "Frame")
    ratio = meta.get("ratio")
    content.append({"type": "text", "text": PROMPT.format(
        name=meta.get("name") or meta.get("channel") or "?", platform=meta.get("platform") or "?",
        title=meta.get("title") or "(unknown)", hook=cap.get("hook") or "(none)", length=length,
        ratio=f"{ratio:.1f}x" if isinstance(ratio, (int, float)) else "(unknown)",
        video=_describe(video), transcript=transcript[:3000], chat=chat_curve(meta, length))})
    d = await _ask(model, [{"role": "user", "content": content}], SCHEMA) if frames else None
    if not d:
        return {**result, "verdict": "unsure", "score": None, "by": "none",
                "what_happens": "", "why": "The AI couldn't look at this clip (check the AI key in Settings)."}
    try:
        score = max(0, min(10, int(d.get("score", 5))))
    except (TypeError, ValueError):
        score = 5
    # Trash when the AI says so and scores it low; a very low score is trash either way. Close calls stay.
    verdict = "trash" if (d.get("verdict") == "trash" and score <= TRASH_SCORE + 1) or score <= 2 else "keep"
    return {**result, "verdict": verdict, "score": score, "by": "ai",
            "what_happens": str(d.get("what_happens", ""))[:200], "why": str(d.get("why", ""))[:240]}


def save(details: Path, verdict: dict) -> None:
    try:
        meta = json.loads(details.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    meta["dull_check"] = verdict
    details.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
