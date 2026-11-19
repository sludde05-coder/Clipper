"""Top 5 (or Top N) compilations: a countdown of the best moments, made from finished phone clips.

    [title card, 2 s]  #5 ...  #4 ...  #3 ...  #2 ...  #1 (the biggest)

Each moment is cut to about 14 s around the moment chat exploded, and gets a big rank number with
the streamer's name in the corner (credit on screen, for every streamer in it). The result is saved
like any other clip, in clips/Top moments/, so it's posted the normal way.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from . import naming
from .captions import ass_color, clean, ts
from .proc import NO_WINDOW
from .vertical import ENCODE_TIMEOUT, PLATFORM_AUDIO, PLATFORM_VIDEO, probe_duration, probe_video_duration

log = logging.getLogger(__name__)

FOLDER = "Top moments"
INTRO = 2.0          # seconds of title card
SEGMENT = 14.0       # longest each moment may be
BEFORE = 10.0        # of which, seconds before the explosion
PLATFORM_NAMES = {"twitch": "Twitch", "youtube": "YouTube", "kick": "Kick"}


def strength(meta: dict) -> float:
    """How big a moment was: how far chat jumped above normal, in messages per second."""
    try:
        return float(meta.get("chat_rate") or 0) - float(meta.get("normal_rate") or 0)
    except (TypeError, ValueError):
        return 0.0


def default_title(n: int) -> str:
    return f"Top {n} GTA 6 moments today 😭"


def _details(clip: Path) -> Path:
    return clip.parent.parent / naming.DETAILS / (clip.stem + ".json")


def load_meta(clip: Path) -> dict:
    try:
        return json.loads(_details(clip).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pick_best(clips_dir: Path, n: int = 5, hours: float = 24) -> list[Path]:
    """The n biggest moments from the last `hours`, biggest first (compilations themselves left out)."""
    since = datetime.now() - timedelta(hours=hours)
    found = []
    for streamer in Path(clips_dir).iterdir() if Path(clips_dir).exists() else []:
        if not streamer.is_dir() or streamer.name in (FOLDER, "Deleted clips") or streamer.name.startswith("."):
            continue
        for clip in (streamer / naming.PHONE).glob("*.mp4"):
            if clip.name.endswith(".rendering.mp4"):
                continue
            meta = load_meta(clip)
            try:
                when = datetime.fromisoformat(meta["explosion_at"])
            except (KeyError, ValueError):
                when = datetime.fromtimestamp(clip.stat().st_mtime)
            if when >= since and not meta.get("compilation"):
                found.append((strength(meta), clip))
    return [c for _, c in sorted(found, key=lambda x: x[0], reverse=True)[:n]]


def window(meta: dict, length: float) -> tuple[float, float]:
    """The part of a phone clip to use: up to SEGMENT seconds, starting a bit before the explosion."""
    off = meta.get("explosion_offset")
    off = float(off) if isinstance(off, (int, float)) else length / 2
    start = min(max(0.0, off - BEFORE), max(0.0, length - SEGMENT))
    return round(start, 2), round(min(length, start + SEGMENT), 2)


def _has_audio(clip: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", str(clip)], capture_output=True, text=True, **NO_WINDOW)
    return bool(r.stdout.strip())


def _badges_ass(parts: list[dict], title: str | None, font: str) -> str:
    """Rank numbers with the streamer's name, top left, popping in at the start of each moment."""
    yellow, black, white = ass_color((255, 214, 0)), ass_color((0, 0, 0)), ass_color((255, 255, 255))
    box = ass_color((0, 0, 0), alpha=0x30)
    out = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Rank,{font},150,{yellow},{yellow},{black},{black},-1,0,0,0,100,100,0,0,1,10,5,7,0,0,0,1",
        f"Style: Who,{font},52,{white},{white},{box},{box},-1,0,0,0,100,100,0,0,3,12,0,7,0,0,0,1",
        f"Style: Title,{font},84,{white},{white},{box},{box},-1,0,0,0,100,100,0,0,3,20,0,5,90,90,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if title:
        out.append(f"Dialogue: 2,{ts(0)},{ts(INTRO)},Title,,0,0,0,,{{\\an5\\pos(540,900)\\fad(150,150)}}{clean(title)}")
    for p in parts:
        pop = "\\fscx40\\fscy40\\t(0,150,\\fscx115\\fscy115)\\t(150,260,\\fscx100\\fscy100)"
        out.append(f"Dialogue: 3,{ts(p['at'])},{ts(p['at'] + p['dur'])},Rank,,0,0,0,,"
                   f"{{\\an7\\pos(48,40){pop}}}#{p['rank']}")
        who = clean(p["who"])
        if who:
            out.append(f"Dialogue: 3,{ts(p['at'])},{ts(p['at'] + p['dur'])},Who,,0,0,0,,"
                       f"{{\\an7\\pos(60,215)\\fad(200,0)}}{who}")
    return "\n".join(out) + "\n"


async def make(clips: list[Path], out: Path, title: str, font: str = "Arial") -> tuple[Path, list[dict]]:
    """Make the countdown from `clips`, biggest moment first in the list (it's shown last, as #1)."""
    from .headline import render
    n = len(clips)
    order = list(reversed(clips))            # #n first ... #1 last
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        args, graph, parts = [], [], []
        # 0: the title card is the first moment, blurred and darkened, with the title on it.
        first_meta = load_meta(order[0])
        first_len = await asyncio.to_thread(probe_duration, order[0])
        s0, _ = window(first_meta, first_len)
        args += ["-ss", f"{s0:.2f}", "-t", f"{INTRO:.2f}", "-i", str(order[0].resolve())]
        size = render(title, tmpd / "title.png") if title.strip() else None
        graph.append("[0:v]setpts=PTS-STARTPTS,fps=30,scale=1080:1920,setsar=1,gblur=sigma=30,"
                     "eq=brightness=-0.18,format=yuv420p[intro0]")
        idx = 1
        if size:
            args += ["-loop", "1", "-framerate", "30", "-i", str(tmpd / "title.png")]
            w, h = size
            graph.append(f"[intro0][{idx}:v]overlay=x={(1080 - w) // 2}:y={900 - h // 2}:shortest=1,format=yuv420p[intro]")
            idx += 1
        else:
            graph.append("[intro0]null[intro]")
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{INTRO},asetpts=N/SR/TB[introa]")
        at = INTRO
        labels = ["[intro][introa]"]
        for k, clip in enumerate(order):
            meta = load_meta(clip)
            length = await asyncio.to_thread(probe_video_duration, clip) or await asyncio.to_thread(probe_duration, clip)
            start, end = window(meta, length)
            dur = max(1.0, end - start)
            args += ["-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(clip.resolve())]
            graph.append(f"[{idx}:v]setpts=PTS-STARTPTS,fps=30,scale=1080:1920,setsar=1,format=yuv420p[v{k}]")
            if await asyncio.to_thread(_has_audio, clip):
                graph.append(f"[{idx}:a]asetpts=PTS-STARTPTS,aresample=48000,"
                             f"aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=0:{dur:.2f}[a{k}]")
            else:
                graph.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{dur:.2f}[a{k}]")
            labels.append(f"[v{k}][a{k}]")
            name = meta.get("name") or clip.parent.parent.name
            where = PLATFORM_NAMES.get(meta.get("platform", ""), "")
            parts.append({"rank": n - k, "at": at, "dur": dur, "who": f"{name}" + (f" · {where}" if where else ""),
                          "name": name, "platform": meta.get("platform", ""), "url": meta.get("url", ""),
                          "clip": clip.name, "hook": (meta.get("captions") or {}).get("hook", "")})
            at += dur
            idx += 1
        (tmpd / "badges.ass").write_text(_badges_ass(parts, None if size else title, font), encoding="utf-8")
        graph.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=1[cv][ca]")
        graph.append("[cv]ass=badges.ass[v]")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = out.with_name(out.stem + ".rendering.mp4")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args,
            "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[ca]",
            *PLATFORM_VIDEO, "-preset", "medium", "-crf", "20", *PLATFORM_AUDIO,
            "-movflags", "+faststart", str(tmp_out.resolve()),
            cwd=tmp, stderr=asyncio.subprocess.PIPE, **NO_WINDOW)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), ENCODE_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            tmp_out.unlink(missing_ok=True)
            raise RuntimeError("making the compilation took too long and was stopped")
        if proc.returncode != 0 or probe_video_duration(tmp_out) < at - 2:
            tmp_out.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg couldn't make the compilation: {err.decode(errors='replace')[-300:]}")
        tmp_out.replace(out)
    return out, parts


def post_texts(title: str, parts: list[dict]) -> dict:
    """What's posted with it: the title, a question for comments, and a credit for every streamer."""
    ranked = sorted(parts, key=lambda p: p["rank"], reverse=True)
    credits = " · ".join(f"#{p['rank']} {p['name']}" + (f" ({PLATFORM_NAMES[p['platform']]})" if p["platform"] in PLATFORM_NAMES else "")
                         for p in ranked)
    names = list(dict.fromkeys(p["name"] for p in ranked))
    tags = ["#gta6", "#gta6clips", f"#top{len(parts)}"]
    return {
        "tiktok": f"{title}\nWhich one was the best? 👇\n🎥 {credits}",
        "instagram": f"{title}\nWhich one was the best? 👇\n\n🎥 {credits}",
        "youtube_title": title[:60],
        "youtube_description": "\n".join([f"{title}. Which one was the best?", "",
                                          *[f"#{p['rank']} {p['name']}" + (f": {p['url']}" if p["url"] else "")
                                            for p in ranked]]),
        "hashtags": tags + [f"#{''.join(ch for ch in nm.lower() if ch.isalnum())}" for nm in names[:3]],
    }


async def build(clips_dir: Path, clips: list[Path], title: str = "", font: str = "Arial") -> Path:
    """Make a compilation of `clips` (any order: they're ranked by how big the moment was) and file it in
    clips/Top moments/ with its details, ready to post like any other clip."""
    if len(clips) < 2:
        raise ValueError("pick at least 2 clips")
    clips = sorted(clips[:10], key=lambda c: strength(load_meta(c)), reverse=True)
    title = title.strip() or default_title(len(clips))
    folder = Path(clips_dir) / FOLDER
    number = naming.next_number(folder)
    name = f"Top_moments_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{number}"
    out = folder / naming.PHONE / f"{name}.mp4"
    out, parts = await make(clips, out, title, font)
    naming.commit_number(folder, number)
    meta = {
        "name": "", "folder": FOLDER, "compilation": parts, "explosion_offset": 1.0,
        "explosion_at": datetime.now().isoformat(timespec="seconds"), "vertical": out.name,
        "captions": {"hook": title, "mood": "hype", "beats": [], "emphasis": [], "layout": "blur", "words": []},
        "ai_post": post_texts(title, parts),
    }
    details = _details(out)
    details.parent.mkdir(parents=True, exist_ok=True)
    details.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("🏆 made %s: %s", out.name, ", ".join(f"#{p['rank']} {p['name']}" for p in sorted(parts, key=lambda p: -p["rank"])))
    return out
