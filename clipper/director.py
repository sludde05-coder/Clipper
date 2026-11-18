"""Decides what the captions should say, based on what happens in the clip.

With an Anthropic API key, Claude looks at frames from the clip, the speech
transcript and the chat around the explosion, and writes:
  - a hook headline for the top of the video
  - short reaction "beats" timed to key moments ("HE MISSED THE JUMP")
  - which words to highlight, the mood, where to crop, and a post caption.

Without a key, a rule-based fallback reads the chat's emotes to pick the mood
and fills in templates.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .transcribe import Word
from .proc import NO_WINDOW

log = logging.getLogger(__name__)

MOODS = ["funny", "hype", "shock", "rage", "sad", "wholesome"]

# Chat vocabulary per mood (matched case-insensitively against whole tokens).
MOOD_WORDS = {
    "funny": {"kekw", "lul", "lmao", "lmfao", "omegalul", "icant", "lol", "haha", "hahaha", "xd", "😂", "🤣",
              "kekl", "pepelaugh", "lulw", "dead", "💀"},
    "hype": {"pog", "poggers", "pogchamp", "w", "ww", "www", "goat", "hype", "letsgo", "lets", "🔥", "ez",
             "clutch", "insane", "cracked", "huge", "🐐"},
    "shock": {"wtf", "no", "way", "what", "?", "??", "???", "holy", "monkas", "omg", "😱", "😳", "bro", "huh"},
    "rage": {"madge", "bruh", "trash", "l", "ll", "ratio", "😡", "copium", "throw", "threw"},
    "sad": {"f", "rip", "sadge", "😢", "😭", "pain", "nooo", "noooo", "unlucky"},
    "wholesome": {"❤", "❤️", "<3", "aww", "cute", "wholesome", "love", "🥺", "peepohappy"},
}

# Fallback headlines (no AI): several per mood, picked at random so clips don't all read the same.
HOOKS = {
    "funny": ["{name} could not stop laughing", "I can't believe this happened", "{name} was NOT ready for this",
              "This is why we watch {name}", "Nobody saw that coming", "{name} lost it"],
    "hype": ["{name} actually pulled it off", "This might be the play of the day", "{name} just went crazy",
             "Clean. Absolutely clean.", "Tell me this isn't insane", "{name} said watch this"],
    "shock": ["Wait… what just happened?", "{name} did NOT see that coming", "Nobody was ready for this",
              "This changed everything", "{name} froze for a second", "Rewind that again"],
    "rage": ["{name} is so done", "This is going to hurt", "{name} had enough", "And it all fell apart"],
    "sad": ["This one hurt", "So close…", "{name} will remember this one", "Pain."],
    "wholesome": ["This made my day", "{name} is the best", "Okay this was really sweet", "Faith in humanity restored"],
}


def pick_hook(mood: str, name: str) -> str:
    import random
    return random.choice(HOOKS.get(mood, HOOKS["hype"])).format(name=name or "They")

EMOJI = {"funny": "😂", "hype": "🔥", "shock": "😱", "rage": "😡", "sad": "💔", "wholesome": "🥹"}


@dataclass
class Beat:
    t: float      # seconds from clip start
    text: str


@dataclass
class Plan:
    hook: str
    mood: str
    beats: list[Beat] = field(default_factory=list)
    emphasis: list[str] = field(default_factory=list)
    crop_focus_x: float = 0.5
    post_caption: str = ""
    source: str = "rules"


# ---------------- rule-based fallback ----------------

def _tokens(text: str) -> list[str]:
    text = text.lower()
    toks = re.findall(r"[a-z0-9<']+|\?+|[^\s\w]", text)
    out = []
    for t in toks:
        out.append(t)
        if re.fullmatch(r"w+", t):
            out.append("w")
    return out


def chat_mood(messages: list[str]) -> tuple[str, Counter]:
    scores: Counter = Counter()
    for m in messages:
        toks = set(_tokens(m))
        if "lets" in toks and "go" in toks:
            toks.add("letsgo")
        for mood, vocab in MOOD_WORDS.items():
            if toks & vocab:
                scores[mood] += 1
    mood = scores.most_common(1)[0][0] if scores else "hype"
    return mood, scores


def rule_plan(meta: dict, words: list[Word]) -> Plan:
    timeline = meta.get("chat_timeline") or []
    texts = [t[2] for t in timeline] or [s.split(": ", 1)[-1] for s in meta.get("chat_sample", [])]
    mood, _ = chat_mood(texts)
    name = meta.get("name") or meta.get("channel", "Streamer")
    offset = float(meta.get("explosion_offset", 30))
    # A short "wait for it" right before the moment, instead of quoting chat.
    beats = [Beat(max(0.5, offset - 4), "WAIT FOR IT")] if offset > 6 else []
    return Plan(hook=pick_hook(mood, name), mood=mood, beats=beats,
                post_caption=f"{name} {EMOJI[mood]} #gta6 #{meta.get('platform', '')} #clips",
                source="rules")


# ---------------- Claude ----------------

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hook", "mood", "beats", "emphasis", "crop_focus_x", "post_caption"],
    "properties": {
        "hook": {"type": "string", "description": "Text above the video about what the streamer did or said. Max 8 words."},
        "mood": {"type": "string", "enum": MOODS},
        "beats": {
            "type": "array",
            "description": "0-2 short captions at key moments.",
            "items": {"type": "object", "additionalProperties": False, "required": ["t", "text"],
                      "properties": {"t": {"type": "number"}, "text": {"type": "string"}}},
        },
        "emphasis": {"type": "array", "items": {"type": "string"},
                     "description": "Up to 6 spoken words worth highlighting."},
        "crop_focus_x": {"type": "number", "description": "0=left edge, 0.5=center, 1=right edge"},
        "post_caption": {"type": "string"},
    },
}

PROMPT = """You are a skilled clip editor turning a livestream moment into a vertical short (TikTok/Shorts/Reels).
The clip was cut automatically because the stream's chat suddenly exploded, so something big happened
just before t={offset:.0f}s. Chat is only how the moment was found: it is NOT the story.

Streamer: {name} ({platform})
Stream title: {title}
Clip length: {length:.0f}s

What the streamer says (speech-to-text, t = seconds from clip start):
{transcript}

Chat around the explosion (use it only to understand the mood):
{chat}

The images are frames from the clip, labelled with their timestamps. Most are from just before the explosion.

First work out what actually happened: what the streamer did, said, saw or reacted to. Then write:

- hook: the text shown above the video for the whole clip. It must make someone stop scrolling.
  * It's about the streamer and the moment, never about chat. Do not use the word "chat".
  * Write like a sharp human clipper, casual and specific, not like a news headline or a template.
  * Pick whichever style fits THIS moment best, and vary it from clip to clip:
    a funny or dramatic line the streamer actually said (quoted), a reaction ("he did NOT see that coming"),
    a setup ("POV: you trust the NPC"), a bold claim, or a short question.
  * Be concrete about what happened. Use the streamer's name only when it adds something.
  * Max 8 words. No hashtags, no emoji.
{recent}
- mood: the overall feel of the moment.
- beats: 0-2 short on-screen captions (max 5 words each, no emoji), timed to the key moments you can
  see or hear, e.g. right before the big moment ("wait for it") or the payoff. Not about chat, and don't
  repeat the hook. Leave beats empty if the speech captions already tell the story.
- emphasis: words from the transcript worth highlighting (the punchline, names, key words).
- crop_focus_x: if the video is cropped to a vertical strip, where should its center be so the action stays in frame?
- post_caption: one natural line to post with the clip, in the same voice as the hook but not a copy of it,
  followed by 3-5 relevant hashtags."""

RETRY = ("Your hook \"{hook}\" is about chat or reuses a recent pattern. Write a new set where the hook is about "
         "what the streamer did or said in this moment, without the word \"chat\".")


def hook_is_weak(hook: str, recent: list[str]) -> bool:
    """A hook about chat, or one that opens like a recent one, gets one retry."""
    h = hook.lower().strip()
    if not h or re.search(r"\bchat\b", h):
        return True
    opening = " ".join(h.split()[:2])
    return any(" ".join(r.lower().split()[:2]) == opening for r in recent[-5:]) and len(h.split()) > 2


FALLBACK_MODELS = ("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")


def _extract_frames(clip: Path, times: list[float], width: int = 640) -> list[tuple[float, str]]:
    frames = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(clip),
                            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "5", "-f", "mjpeg", "pipe:1"],
                           capture_output=True, **NO_WINDOW)
        if r.returncode == 0 and r.stdout:
            frames.append((t, base64.b64encode(r.stdout).decode()))
    return frames


async def claude_plan(clip: Path, meta: dict, words: list[Word], length: float, model: str,
                      recent: list[str] | None = None) -> Plan | None:
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic not installed: using rule-based captions")
        return None
    offset = float(meta.get("explosion_offset", 30))
    times = sorted({round(min(max(0.5, offset + d), length - 0.5), 1) for d in (-12, -7, -4, -2, 0, 2, 6)})
    frames = await asyncio.to_thread(_extract_frames, clip, times)

    transcript = "\n".join(_lines(words)) or "(no speech detected)"
    chat = "\n".join(f"t={t:5.1f}  {u}: {m}" for t, u, m in (meta.get("chat_timeline") or [])[:120]) \
        or "\n".join(meta.get("chat_sample", [])) or "(none)"
    content: list[dict] = []
    for t, b64 in frames:
        content.append({"type": "text", "text": f"Frame at t={t:.1f}s"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    recent = recent or []
    recent_text = ("  * Recent hooks. Don't reuse their wording, structure or opening words:\n"
                   + "\n".join(f"      - {h}" for h in recent[-12:])) if recent else ""
    content.append({"type": "text", "text": PROMPT.format(
        name=meta.get("name") or meta.get("channel"), platform=meta.get("platform"),
        title=meta.get("title") or "(unknown)", length=length, offset=offset,
        transcript=transcript, chat=chat, recent=recent_text)})
    messages = [{"role": "user", "content": content}]

    d = await _ask(model, messages)
    if d is not None and hook_is_weak(d.get("hook", ""), recent):
        messages += [{"role": "assistant", "content": json.dumps(d)},
                     {"role": "user", "content": RETRY.format(hook=d.get("hook", ""))}]
        d = await _ask(model, messages) or d
    if d is None:
        return None
    mood = d.get("mood") if d.get("mood") in MOODS else "hype"
    return Plan(
        hook=d.get("hook", "").strip() or pick_hook(mood, meta.get("name", "")),
        mood=mood,
        beats=[Beat(float(b["t"]), b["text"]) for b in d.get("beats", [])[:2]
               if 0 <= float(b.get("t", -1)) < length and b.get("text")],
        emphasis=[w.lower() for w in d.get("emphasis", [])][:6],
        crop_focus_x=min(1.0, max(0.0, float(d.get("crop_focus_x", 0.5)))),
        post_caption=d.get("post_caption", ""),
        source="claude",
    )


async def _ask(model: str, messages: list[dict]) -> dict | None:
    import anthropic

    try:
        client = anthropic.AsyncAnthropic()
        # If the model declines, the API retries on a fallback model. Haiku has no
        # server-side fallback, so the option is only sent where it exists.
        fallback = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
                    if model.startswith(FALLBACK_MODELS) else {})
        resp = await client.beta.messages.create(
            model=model,
            max_tokens=16000,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=messages,
            **fallback,
        )
    except anthropic.AuthenticationError:
        log.warning("no valid Anthropic API key: using rule-based captions (set ANTHROPIC_API_KEY)")
        return None
    except anthropic.RateLimitError:
        log.warning("Claude rate limited: using rule-based captions for this clip")
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude request failed (%s): using rule-based captions", e.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("couldn't reach the Claude API: using rule-based captions")
        return None
    except (anthropic.AnthropicError, TypeError) as e:  # TypeError: no API key configured at all
        log.warning("Claude unavailable (%s): using rule-based captions", str(e).split(".")[0])
        return None
    if resp.stop_reason != "end_turn":
        log.warning("Claude stopped with %s: using rule-based captions", resp.stop_reason)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned unparseable JSON: using rule-based captions")
        return None


def _lines(words: list[Word]) -> list[str]:
    lines, cur, start = [], [], 0.0
    for w in words:
        if not cur:
            start = w.start
        cur.append(w.text)
        if w.text.endswith((".", "!", "?")) or len(cur) >= 14:
            lines.append(f"t={start:5.1f}  {' '.join(cur)}")
            cur = []
    if cur:
        lines.append(f"t={start:5.1f}  {' '.join(cur)}")
    return lines
