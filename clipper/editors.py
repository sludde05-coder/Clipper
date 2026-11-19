"""The AI editing team. Five copies of the same model, each with one job, like an editing crew:

  1. Trim editor      where the moment really starts and ends           } run side by side
  2. Facecam editor   where the streamer's webcam is, and the action     }
  3. Caption editor   headline, reaction captions, highlights (director.claude_plan)  } side by side
  4. Post editor      the TikTok / YouTube / Instagram texts                           }
  5. Review editor    looks at the finished video and asks for fixes (one round)

Every editor has a time limit through the shared request helper, and if one can't answer the clip
is still made with that step's sensible default, so nothing ever blocks on the AI.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .director import _ask, _extract_frames, _lines
from .transcribe import Word

log = logging.getLogger(__name__)

MIN_LEN, MAX_LEN = 10.0, 50.0   # seconds the trim editor may choose between


def _image(content: list, t: float, b64: str, label: str = "Frame") -> None:
    content.append({"type": "text", "text": f"{label} at t={t:.1f}s"})
    content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})


def chat_curve(meta: dict, length: float, step: float = 2.0) -> str:
    """Messages per 2 seconds across the clip, plus the most repeated ones in each burst."""
    timeline = meta.get("chat_timeline") or []
    if not timeline:
        return "(no chat recorded)"
    bins: dict[int, list[str]] = {}
    for t, _user, msg in timeline:
        bins.setdefault(int(float(t) // step), []).append(msg)
    rows = []
    for i in range(int(length // step) + 1):
        msgs = bins.get(i, [])
        top = ", ".join(m for m, _ in Counter(x.strip().upper()[:20] for x in msgs).most_common(2)) if msgs else ""
        rows.append(f"t={i * step:4.0f}-{(i + 1) * step:<3.0f} {len(msgs):3d} msgs {top}")
    return "\n".join(rows)


# ---------------------------------------------------------------- 1. trim

@dataclass
class Trim:
    start: float
    end: float
    why: str = ""
    source: str = "default"


def default_trim(offset: float, length: float, before: float, after: float) -> Trim:
    """Without the AI: the usual window around the explosion (e.g. 22 s before, 8 s after)."""
    return Trim(max(0.0, offset - before), min(length, offset + after), "default window", "default")


TRIM_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["start", "end", "why"],
    "properties": {"start": {"type": "number"}, "end": {"type": "number"}, "why": {"type": "string"}},
}

TRIM_PROMPT = """You are the trim editor on a team cutting livestream moments into viral shorts. You only decide
where the clip starts and ends. Others do captions and layout.

The recording is {length:.0f}s long. Chat exploded at t={offset:.0f}s, so the moment that caused it is just before.
Streamer: {name}. Stream title: {title}

What the streamer says (t = seconds from the start of the recording):
{transcript}

Chat activity across the recording:
{curve}

The images are frames across the recording, with their times.

Choose start and end (seconds) so the clip is the moment and nothing else:
- Start right where the setup of THIS moment begins: no dead air, no unrelated talk before it. Viewers decide in the
  first second, so start as close to the action as possible while keeping what's needed to understand it.
- End shortly after the payoff and the streamer's reaction peak; cut before it fizzles out.
- It must include t={must_from:.0f}s to t={must_to:.0f}s. Between {min_len:.0f} and {max_len:.0f} seconds long; usually 15-35.
- why: one short sentence on what happens in the cut."""


async def trim_editor(clip: Path, meta: dict, words: list[Word], length: float, model: str) -> Trim | None:
    offset = float(meta.get("explosion_offset", length * 0.7))
    step = max(2.5, length / 14)
    times = [round(min(length - 0.3, 0.5 + i * step), 1) for i in range(int(length // step) + 1)]
    frames = await asyncio.to_thread(_extract_frames, clip, times, 384)
    content: list[dict] = []
    for t, b64 in frames:
        _image(content, t, b64)
    must_from, must_to = max(0.0, offset - 3), min(length, offset + 2)
    content.append({"type": "text", "text": TRIM_PROMPT.format(
        length=length, offset=offset, name=meta.get("name", ""), title=meta.get("title") or "(unknown)",
        transcript="\n".join(_lines(words)) or "(no speech detected)", curve=chat_curve(meta, length),
        must_from=must_from, must_to=must_to, min_len=MIN_LEN, max_len=MAX_LEN)})
    d = await _ask(model, [{"role": "user", "content": content}], TRIM_SCHEMA)
    if not d:
        return None
    try:
        start, end = float(d["start"]), float(d["end"])
    except (KeyError, TypeError, ValueError):
        return None
    # Keep it sane whatever came back.
    start = max(0.0, min(start, must_from))
    end = min(length, max(end, must_to))
    if end - start > MAX_LEN:
        start = max(start, end - MAX_LEN)
    if end - start < MIN_LEN:
        pad = (MIN_LEN - (end - start)) / 2
        start, end = max(0.0, start - pad), min(length, end + pad)
    return Trim(round(start, 2), round(end, 2), str(d.get("why", ""))[:200], "ai")


# ---------------------------------------------------------------- 2. facecam

FACECAM_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["has_facecam", "x", "y", "w", "h", "action_x"],
    "properties": {"has_facecam": {"type": "boolean"}, "x": {"type": "number"}, "y": {"type": "number"},
                   "w": {"type": "number"}, "h": {"type": "number"}, "action_x": {"type": "number"}},
}

FACECAM_PROMPT = """You are the layout editor on a team cutting livestream moments into vertical shorts. The final
video puts the streamer's webcam on top and the gameplay below.

Look at these frames from a stream. Many streamers show their webcam as a small box over the game
(usually in a corner). Some don't have one, and some are "just chatting" with the camera filling the screen.

- has_facecam: true only if there is a webcam box showing the streamer over the gameplay.
- x, y, w, h: the webcam box as fractions of the frame (0-1): left edge, top edge, width, height.
  Fit it tightly to the camera image itself, not its border or any overlay around it.
  If there's no webcam box, give 0 for all four.
- action_x: where the important gameplay is, across the frame (0 = left edge, 0.5 = middle, 1 = right edge)."""


async def facecam_editor(clip: Path, length: float, model: str) -> tuple[list | None, float] | None:
    times = sorted({round(length * f, 1) for f in (0.2, 0.5, 0.8)})
    frames = await asyncio.to_thread(_extract_frames, clip, times, 768)
    if not frames:
        return None
    content: list[dict] = []
    for t, b64 in frames:
        _image(content, t, b64)
    content.append({"type": "text", "text": FACECAM_PROMPT})
    d = await _ask(model, [{"role": "user", "content": content}], FACECAM_SCHEMA)
    if not d:
        return None
    action_x = min(1.0, max(0.0, float(d.get("action_x", 0.5) or 0.5)))
    box = None
    try:
        x, y, w, h = (float(d[k]) for k in ("x", "y", "w", "h"))
        # A believable webcam box: inside the frame, not tiny, not the whole screen.
        if d.get("has_facecam") and 0.06 <= w <= 0.6 and 0.06 <= h <= 0.6 and x >= 0 and y >= 0 \
                and x + w <= 1.001 and y + h <= 1.001:
            box = [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]
    except (KeyError, TypeError, ValueError):
        pass
    return box, action_x


# ---------------------------------------------------------------- 4. post text

POST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["tiktok", "instagram", "youtube_title", "youtube_description", "hashtags"],
    "properties": {"tiktok": {"type": "string"}, "instagram": {"type": "string"},
                   "youtube_title": {"type": "string"}, "youtube_description": {"type": "string"},
                   "hashtags": {"type": "array", "items": {"type": "string"}}},
}

POST_PROMPT = """You are the post editor on a team publishing viral livestream clips. You write only the text that goes
with the video on each platform, in the voice of the best clip accounts: like a viewer texting a friend, casual,
specific to this clip, never like an ad or a news headline. Don't use "chat", "epic", "insane moment", "went crazy",
"play of the day", "you won't believe".
Platform safety: never mention sex or sexual things (sex toys, strippers, porn, nudes...), drugs or smoking
  (weed, bongs, getting high...), self-harm or suicide, even as a joke, even if the streamer said it. TikTok, YouTube and
  Instagram take those videos down and warn the account. Describe the moment another way or pick another angle.

Streamer: {name} ({platform}). Stream title: {title}
On-screen headline (written by the caption editor): {hook}
What happens: {why}
What the streamer says:
{transcript}

Write:
- tiktok: 1-2 casual sentences (about 80-180 characters) in the same clipper style as the headline: start with
  what {name} did ("{name} tried to rob a bank with a golf club 😭"), then a joke or a question that gets comments.
  Mention "gta 6" naturally (people search for it). 1-2 emoji at most. No hashtags here.
- instagram: same idea, a little more polished, 1-2 sentences. No hashtags here.
- youtube_title: a Shorts title, max 60 characters, curiosity-driven, no hashtags, not just the headline again.
- youtube_description: 1-2 sentences of context for the clip.
- hashtags: 3-5 relevant hashtags, lowercase, starting with #gta6."""


async def post_editor(meta: dict, hook: str, why: str, words: list[Word], model: str) -> dict | None:
    content = [{"type": "text", "text": POST_PROMPT.format(
        name=meta.get("name") or meta.get("channel") or "the streamer", platform=meta.get("platform", ""),
        title=meta.get("title") or "(unknown)", hook=hook or "(none)", why=why or "(see transcript)",
        transcript="\n".join(_lines(words))[:3000] or "(no speech detected)")}]
    d = await _ask(model, [{"role": "user", "content": content}], POST_SCHEMA)
    if not d:
        return None
    tags = [t if t.startswith("#") else f"#{t}" for t in d.get("hashtags", []) if str(t).strip("# ")][:5]
    return {"tiktok": str(d.get("tiktok", "")).strip(), "instagram": str(d.get("instagram", "")).strip(),
            "youtube_title": str(d.get("youtube_title", "")).strip()[:70],
            "youtube_description": str(d.get("youtube_description", "")).strip(), "hashtags": tags}


# ---------------------------------------------------------------- 5. review

REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["ok", "issues", "new_hook", "layout", "drop_beats"],
    "properties": {"ok": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}},
                   "new_hook": {"type": "string"},
                   "layout": {"type": "string", "enum": ["keep", "blur", "crop"]},
                   "drop_beats": {"type": "boolean"}},
}

REVIEW_PROMPT = """You are the final reviewer on a team making viral livestream shorts. These are frames from the
FINISHED vertical video, about to be posted. The team's plan:
- Headline on screen: "{hook}"
- Layout: {layout}
- Reaction captions: {beats}

Check it like a picky senior editor:
- Is the headline readable and not covering the streamer's face or the key action?
- With the webcam-on-top layout: does the top part actually show the streamer's face? If it shows game UI, a logo,
  something cut in half or nothing useful, the webcam crop is wrong: answer layout "blur".
- Is the headline in the clipper format, specific to this clip? It should read either "<Streamer> did <specific
  thing>" with one emoji at the end ("Kai went on a date in GTA 6 😭"), or a question about the game ("You can get
  a job in GTA 6?????"). If it describes the video like a narrator, is generic or robotic, write a better one in
  new_hook (5-12 words, that format, never "chat"). Otherwise leave new_hook empty.
- Does the headline mention sex, drugs, smoking, self-harm or anything else the platforms take videos down for?
  Then write a safe one in new_hook.
- Are the reaction captions in the way or pointless? Then drop_beats true.
ok is true only if nothing needs changing. issues: short notes on what's wrong (empty if ok)."""


async def review_editor(phone: Path, length: float, hook: str, layout: str, beats: list, model: str) -> dict | None:
    times = sorted({round(min(length - 0.4, max(0.4, length * f)), 1) for f in (0.05, 0.35, 0.65, 0.95)})
    frames = await asyncio.to_thread(_extract_frames, phone, times, 540)
    if not frames:
        return None
    content: list[dict] = []
    for t, b64 in frames:
        _image(content, t, b64, "Finished video frame")
    content.append({"type": "text", "text": REVIEW_PROMPT.format(
        hook=hook, layout={"facecam": "webcam on top, gameplay below",
                           "facecam_full": "webcam on top, the whole stream screen below over a blurred background",
                           "blur": "whole picture over a blurred background",
                           "crop": "gameplay cropped to fill the screen"}.get(layout, layout),
        beats=json.dumps([b.text if hasattr(b, "text") else b for b in beats], ensure_ascii=False) or "none")})
    d = await _ask(model, [{"role": "user", "content": content}], REVIEW_SCHEMA)
    if not d:
        return None
    return {"ok": bool(d.get("ok")), "issues": [str(i) for i in d.get("issues", [])][:5],
            "new_hook": str(d.get("new_hook", "")).strip()[:80], "layout": d.get("layout", "keep"),
            "drop_beats": bool(d.get("drop_beats"))}
