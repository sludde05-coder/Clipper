"""Draws the headline as a picture, so it can end in a real colour emoji ("Kai went on a date in GTA 6 😭").

The subtitle renderer that draws the other captions can't show colour emoji (they come out as empty
boxes), so the headline is drawn here with Pillow: white bold text on dark rounded boxes, one per
line, with the emoji from the computer's emoji font (Segoe UI Emoji on Windows). If Pillow or the
fonts aren't there, the headline goes back to being a normal caption without the emoji.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

from .captions import censor

log = logging.getLogger(__name__)

SIZE = 70          # text size on the 1080x1920 canvas
MAX_WIDTH = 900    # widest a line may be, box included
PAD_X, PAD_Y = 22, 12
BOX = (0, 0, 0, 205)

_EMOJI_CHAR = "\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\u2194-\u21AA\u2934\u2935\u3030\u303D\u3297\u3299"
EMOJI = re.compile(f"[{_EMOJI_CHAR}][\uFE0F\U0001F3FB-\U0001F3FF]*(?:\u200D[{_EMOJI_CHAR}][\uFE0F]*)*")


def _fonts() -> tuple[str | None, str | None]:
    """(bold text font, colour emoji font) on this computer."""
    if sys.platform == "win32":
        d = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        text = [d / "arialbd.ttf", d / "segoeuib.ttf"]
        emoji = [d / "seguiemj.ttf"]
    elif sys.platform == "darwin":
        text = [Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"), Path("/Library/Fonts/Arial Bold.ttf")]
        emoji = [Path("/System/Library/Fonts/Apple Color Emoji.ttc")]
    else:
        text = [Path("/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")]
        emoji = [Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
                 Path("/usr/share/fonts/noto/NotoColorEmoji.ttf")]
    pick = lambda paths: next((str(p) for p in paths if p.exists()), None)  # noqa: E731
    return pick(text), pick(emoji)


def _emoji_picture(cluster: str, font_path: str, height: int):
    """One emoji as an RGBA picture `height` pixels tall, or None if this computer can't draw it.
    Colour emoji fonts only come in some sizes (Noto: 109, Apple: 160/96/64...), so draw at one that
    works and scale it."""
    from PIL import Image, ImageDraw, ImageFont
    for size in (height, 109, 160, 96, 64):
        try:
            font = ImageFont.truetype(font_path, size)
            box = font.getbbox(cluster)
            w, h = box[2] - box[0], box[3] - box[1]
            if w <= 0 or h <= 0:
                continue
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((-box[0], -box[1]), cluster, font=font, embedded_color=True)
        except (OSError, ValueError):
            continue
        if img.getbbox() is None:      # drew nothing
            return None
        return img.resize((max(1, round(w * height / h)), height), Image.LANCZOS)
    return None


def render(text: str, out: Path) -> tuple[int, int] | None:
    """Draw the headline to `out` (a transparent PNG). Returns its (width, height), or None if it
    can't be drawn here (then the caller uses a plain caption instead)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    text = " ".join(censor(text).split())
    if not text:
        return None
    text_font, emoji_font = _fonts()
    try:
        font = ImageFont.truetype(text_font, SIZE) if text_font else ImageFont.load_default(SIZE)
    except (OSError, TypeError, AttributeError):
        return None
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    emoji_h = round(SIZE * 0.95)
    cache: dict[str, object] = {}

    def pieces(word: str) -> list:
        """A word split into text and emoji pictures."""
        out_, pos = [], 0
        for m in EMOJI.finditer(word):
            if m.start() > pos:
                out_.append(word[pos:m.start()])
            c = m.group(0)
            if c not in cache:
                cache[c] = _emoji_picture(c, emoji_font, emoji_h) if emoji_font else None
            if cache[c] is not None:
                out_.append(cache[c])
            pos = m.end()
        if pos < len(word):
            out_.append(word[pos:])
        return out_

    def width(parts: list) -> int:
        return sum(int(font.getlength(p)) if isinstance(p, str) else p.width + 4 for p in parts)

    space = int(font.getlength(" "))
    words = [p for p in (pieces(w) for w in text.split()) if p]
    if not words:
        return None
    lines: list[list[list]] = [[]]
    for w in words:
        cur = lines[-1]
        trial = sum(width(x) for x in cur) + space * len(cur) + width(w)
        if cur and trial > MAX_WIDTH - 2 * PAD_X:
            lines.append([w])
        else:
            cur.append(w)

    line_w = [sum(width(x) for x in ln) + space * (len(ln) - 1) for ln in lines]
    box_h = line_h + 2 * PAD_Y
    W = min(MAX_WIDTH, max(line_w) + 2 * PAD_X)
    H = box_h * len(lines)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, (ln, lw) in enumerate(zip(lines, line_w)):
        bw = min(W, lw + 2 * PAD_X)
        x0, y0 = (W - bw) // 2, i * box_h
        draw.rounded_rectangle((x0, y0, x0 + bw - 1, y0 + box_h - 1), radius=16, fill=BOX)
        x = x0 + PAD_X
        for j, w in enumerate(ln):
            for p in w:
                if isinstance(p, str):
                    draw.text((x, y0 + PAD_Y), p, font=font, fill=(255, 255, 255, 255))
                    x += int(font.getlength(p))
                else:
                    img.alpha_composite(p, (x + 2, y0 + PAD_Y + (line_h - p.height) // 2))
                    x += p.width + 4
            if j < len(ln) - 1:
                x += space
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return W, H
