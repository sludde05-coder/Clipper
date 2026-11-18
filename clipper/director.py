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
# Fallback text when the AI isn't available: several per mood, in a clipper's voice, picked at random.
HOOKS = {
    "funny": ["{name} was not ready for this in GTA 6 😭", "{name} really thought that would work 😭",
              "{name} got humbled in GTA 6 😂", "{name} can't catch a break in GTA 6 😭"],
    "hype": ["{name} pulled this off first try in GTA 6 🔥", "{name} made this look easy in GTA 6 😳",
             "{name} did NOT miss in GTA 6 🔥"],
    "shock": ["{name} did not see that coming in GTA 6 😳", "{name} found out the hard way in GTA 6 💀",
              "This happens in GTA 6?????"],
    "rage": ["{name} is so done with GTA 6 😭", "{name} had one job in GTA 6 💀"],
    "sad": ["{name} was so close in GTA 6 😭", "{name} will never recover from this 💔"],
    "wholesome": ["{name} is too nice for GTA 6 🥹", "{name} made a friend in GTA 6 🥹"],
}
POST_LINES = {
    "funny": ["{name} was not ready for this one in gta 6 😭", "i can't stop watching {name} here in gta 6 😭 who did it better?",
              "{name} really thought that would work in gta 6 💀"],
    "hype": ["{name} made that look easy in gta 6 🔥 could you pull this off?", "that was way too clean from {name} in gta 6 🔥",
             "{name} said watch this and then actually did it in gta 6 😳"],
    "shock": ["{name} did NOT see that coming in gta 6 😳 what would you have done?", "wait for {name}'s reaction in gta 6 😳",
              "how did this even happen to {name} in gta 6 💀"],
    "rage": ["{name} is so done with gta 6 right now 😭", "worst timing ever for {name} in gta 6 💀 whose fault was this?"],
    "sad": ["{name} was so close in gta 6 😭", "this one hurt to watch in gta 6 💔 did {name} deserve better?"],
    "wholesome": ["{name} is too wholesome for gta 6 🥹", "this was actually sweet from {name} in gta 6 🥹"],
}

def pick_hook(mood: str, name: str) -> str:
    import random
    return random.choice(HOOKS.get(mood, HOOKS["hype"])).format(name=name or "bro")


def best_quote(words: list) -> str:
    """A short, punchy line the streamer said (ends in ! or ?, or is short), for a quote hook."""
    lines, cur = [], []
    for w in words:
        cur.append(w.text)
        if w.text.endswith((".", "!", "?")):
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))
    good = [ln.strip(' "') for ln in lines if 2 <= len(ln.split()) <= 7]
    good.sort(key=lambda ln: (not ln.endswith(("!", "?")), len(ln)))
    return good[0] if good else ""

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
    facecam: list | None = None   # [x, y, w, h] as fractions of the frame, if the stream has a webcam


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
    import random
    beats = [Beat(max(0.5, offset - 4), random.choice(["wait for it", "watch this", "here it comes"]).upper())] \
        if offset > 6 else []
    quote = best_quote(words)
    hook = f'"{quote}"' if quote and random.random() < 0.7 else pick_hook(mood, name)
    line = random.choice(POST_LINES.get(mood, POST_LINES["hype"])).format(name=name)
    tags = " ".join(dict.fromkeys(["#gta6", f"#{re.sub(r'[^a-z0-9]', '', name.lower())}", "#gaming", "#fyp"]))
    return Plan(hook=hook, mood=mood, beats=beats, post_caption=f"{line} {tags}", source="rules")


# ---------------- Claude ----------------

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hook_options", "hook", "mood", "beats", "emphasis", "crop_focus_x", "post_caption"],
    "properties": {
        "hook_options": {"type": "array", "items": {"type": "string"},
                         "description": "3 different hooks: a quote, a reaction, a setup."},
        "hook": {"type": "string", "description": "The best of the options. Max 8 words."},
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

PROMPT = """You write the text for viral livestream clips (TikTok, YouTube Shorts, Reels), the way the biggest clip
accounts do. The clip was cut automatically because the stream's chat suddenly exploded, so something big happened
just before t={offset:.0f}s. Chat is only how the moment was found: it is NOT the story.

Streamer: {name} ({platform})
Stream title: {title}
Clip length: {length:.0f}s

What the streamer says (speech-to-text, t = seconds from clip start):
{transcript}

What chat spammed most around the explosion (only to understand the mood): {top_chat}
Chat around the explosion:
{chat}

The images are frames from the clip, labelled with their timestamps. Most are from just before the explosion.

First work out what actually happened: what the streamer did, said, saw or reacted to, and what makes it
funny / shocking / impressive. Then write like a real clipper, not like an AI or a news headline.

HOW THE HEADLINE SOUNDS (the format the biggest clip accounts use)
It is NOT a description of the video. It's one of these two shapes:

(The examples below are made up, to show the format. Never reuse them.)

1. "<Streamer> <did something>" + one emoji at the end. Past tense, about what happened, like gossip:
     {name} went on a date in GTA 6 😭
     {name} got hit on by a few older women 😭
     {name} tried to rob a bank with a golf club 💀
     {name} found out you can buy a house in GTA 6 😳
     {name} got scammed by an NPC 😂
   Start with the streamer's name exactly as written above.

2. A question or statement about the game itself, the kind that makes people who haven't played stop scrolling.
   Usually with several question marks or an emoji:
     You can get a job in GTA 6?????
     NPCs in GTA 6 remember what you did?????
     The cops in GTA 6 are actually insane 💀

Pick the shape that fits the clip: shape 1 when it's about what the streamer did, shape 2 when the moment shows off
something surprising about GTA 6. Write "GTA 6" (capitals) when you mention the game.
- Specific to THIS clip: the actual thing, person or place. Never generic, never narrating ("He walks into...").
- Short: about 5-12 words. Sentence case, not all caps.
- Emoji: exactly one at the end of shape 1 (😭 💀 😂 😳 🤣 are the usual ones; 😭 is the classic for funny).
  Shape 2 ends in ????? or one emoji.
- Never use: "chat", "play of the day", "went crazy", "insane moment", "epic", "absolutely", "you won't believe",
  "wild moment", "chaos", "goes silent", "pulls up", "unbelievable", "legendary", "crazy moment".

Now write:
- hook_options: 3 different headlines in those shapes (at least one of each shape when the clip allows it).
  No hashtags.
- hook: the strongest of the three, the one that makes someone stop scrolling in the first second.
{recent}
- mood: the overall feel of the moment.
- beats: 0-2 short on-screen texts (max 4 words, no emoji, they can't be shown there) timed to key moments, e.g. "wait for it" right before
  the payoff, or a one-word reaction ("BRO.") right after. Not about chat, don't repeat the hook. Empty is fine.
- emphasis: up to 6 words from the transcript worth highlighting (the punchline, names, key words).
- crop_focus_x: if the video is cropped to a vertical strip, where should its center be so the action stays in frame?
- post_caption: what's posted with the clip. 1-2 casual sentences (about 80-200 characters) that add context or
  a joke beyond the hook, mention the streamer's name and "gta 6" naturally (people search for those), and often
  end with a question that gets comments ("would you have stopped?", "who's fault was this?"). 1-2 emoji max
  (😭 💀 🔥 😳 are the usual ones). Then 3-5 hashtags on the same line, lowercase."""

RETRY = ("Your hook \"{hook}\" sounds generic, uses a banned phrase or mentions chat, or reuses a recent opening. "
         "Write a new set in the clipper format: \"<Streamer> did <specific thing> 😭\" or a question about GTA 6 "
         "like \"You can get a job in GTA 6?????\". Specific to this clip, without the word \"chat\".")


BANNED = ("play of the day", "went crazy", "goes crazy", "insane moment", "epic", "absolutely", "you won't believe",
          "wild moment", "chaos", "goes silent", "pulls up", "unbelievable", "legendary", "crazy moment",
          "must watch", "watch till the end", "incredible")


def hook_is_weak(hook: str, recent: list[str]) -> bool:
    """A hook about chat, with stock phrasing, or opening like a recent one gets one retry."""
    h = hook.lower().strip()
    if not h or re.search(r"\bchat\b", h) or any(b in h for b in BANNED):
        return True
    # Headlines start with the streamer's name, so compare the first three words (name + what they did).
    opening = " ".join(h.split()[:3])
    return any(" ".join(r.lower().split()[:3]) == opening for r in recent[-5:]) and len(h.split()) > 3


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
    recent_text = ("  * Recent headlines. Keep the format but don't reuse their wording or the same action:\n"
                   + "\n".join(f"      - {h}" for h in recent[-12:])) if recent else ""
    content.append({"type": "text", "text": PROMPT.format(
        name=meta.get("name") or meta.get("channel"), platform=meta.get("platform"),
        title=meta.get("title") or "(unknown)", length=length, offset=offset,
        transcript=transcript, chat=chat, recent=recent_text, top_chat=top_chat(meta, offset))})
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


async def _ask(model: str, messages: list[dict], schema: dict | None = None) -> dict | None:
    import anthropic

    try:
        client = anthropic.AsyncAnthropic(timeout=180, max_retries=2)
        # If the model declines, the API retries on a fallback model. Haiku has no
        # server-side fallback, so the option is only sent where it exists.
        fallback = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
                    if model.startswith(FALLBACK_MODELS) else {})
        resp = await client.beta.messages.create(
            model=model,
            max_tokens=16000,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema or SCHEMA}},
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


def top_chat(meta: dict, offset: float, n: int = 5) -> str:
    """The most repeated chat messages around the explosion, e.g. 'KEKW ×40, W ×22'."""
    timeline = meta.get("chat_timeline") or []
    texts = [m for tt, _u, m in timeline if offset - 5 <= float(tt) <= offset + 12] or \
            [s.split(": ", 1)[-1] for s in meta.get("chat_sample", [])]
    counts = Counter(re.sub(r"\s+", " ", m.strip().upper())[:30] for m in texts if m.strip())
    return ", ".join(f"{m} ×{c}" for m, c in counts.most_common(n)) or "(none)"


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
