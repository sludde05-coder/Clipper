"""Turns a saved 16:9 clip into a captioned 9:16 video for phones.

  layout "blur": the full frame centered, over a blurred zoomed copy of itself
                 (nothing gets cut off; captions sit above and below the video)
  layout "crop": a vertical slice of the frame, positioned where the action is
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from .captions import build_ass
from .config import VerticalConfig
from .director import Plan, claude_plan, rule_plan
from .transcribe import Transcript, transcribe
from .proc import NO_WINDOW
from . import progress

log = logging.getLogger(__name__)
_slots: asyncio.Semaphore | None = None


def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, **NO_WINDOW)
    return float(r.stdout.strip() or 0)


def probe_video_duration(path: Path) -> float:
    """Length of the picture itself. The file's overall length can be longer when only the
    sound runs the full time, which is how a "1-second" clip can still claim to be 50 s."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=duration:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, **NO_WINDOW)
    try:
        info = json.loads(r.stdout or "{}")
        streams = info.get("streams") or [{}]
        return float(streams[0].get("duration") or info.get("format", {}).get("duration") or 0)
    except (ValueError, TypeError):
        return 0.0


def filter_graph(layout: str, focus_x: float, safe: bool = False) -> str:
    # Safe mode times frames by counting them instead of trusting the video's own clock,
    # which can jump (e.g. around Twitch ad breaks) and make ffmpeg drop most of the video.
    src = "[0:v]setpts=N/FRAME_RATE/TB," if safe else "[0:v]"
    if layout == "crop":
        return (f"{src}scale=-2:1920,crop=1080:1920:x='(iw-1080)*{focus_x:.3f}':y=0,"
                f"setsar=1,ass=captions.ass[v]")
    return (f"{src}split[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            "gblur=sigma=40,eq=brightness=-0.12:saturation=1.2[bg];"
            "[b]scale=1080:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,ass=captions.ass[v]")


RECENT_FILE = ".recent_hooks.json"


def load_recent(folder: Path) -> list[str]:
    try:
        return json.loads((folder / RECENT_FILE).read_text(encoding="utf-8"))[-20:]
    except (OSError, ValueError):
        return []


def remember_hook(folder: Path, hook: str) -> None:
    try:
        (folder / RECENT_FILE).write_text(json.dumps((load_recent(folder) + [hook])[-20:], ensure_ascii=False),
                                         encoding="utf-8")
    except OSError:
        pass


# The safest settings for TikTok / Reels / Shorts uploads, and for picky hardware video decoders
# (e.g. on Snapdragon laptops), which can show a decode they choke on as a green screen:
# H.264 High at level 4.1 (4.0 is right at its limit for 1080x1920), 8-bit 4:2:0 with the colours
# marked as standard HD (BT.709, TV range) instead of left unknown, constant 30 fps, a keyframe every
# 2 seconds starting at the first frame, and stereo AAC at 48 kHz.
PLATFORM_VIDEO = ["-c:v", "libx264", "-profile:v", "high", "-level:v", "4.1", "-pix_fmt", "yuv420p",
                  "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
                  "-r", "30", "-fps_mode", "cfr", "-g", "60", "-keyint_min", "60", "-sc_threshold", "0", "-bf", "2"]
PLATFORM_AUDIO = ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
ENCODE_TIMEOUT = 15 * 60       # a 30 s clip takes under a minute; anything near this is stuck
SPEECH_TIMEOUT = 20 * 60       # includes the one-time ~500 MB model download
_speech_gave_up = False        # after a speech-to-text timeout, skip it for the rest of the session


async def _transcribe_with_limit(clip: Path, model: str) -> Transcript:
    """Speech-to-text, but never wait forever: a slow PC or a stuck download skips word captions."""
    global _speech_gave_up
    if _speech_gave_up:
        return Transcript([])
    try:
        return await asyncio.wait_for(asyncio.to_thread(transcribe, clip, model), SPEECH_TIMEOUT)
    except asyncio.TimeoutError:
        _speech_gave_up = True
        log.warning("speech-to-text took over %d minutes, so clips get no word-by-word captions until Clipper "
                    "restarts. Run the Check tab, or set the speech model to 'base' in Settings.", SPEECH_TIMEOUT // 60)
        return Transcript([])


async def _encode(clip: Path, out: Path, tmp: str, cfg: VerticalConfig, focus_x: float,
                  safe: bool) -> tuple[bool, str]:
    audio = ["-af", "asetpts=N/SR/TB"] if safe else []
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        *(["-fflags", "+genpts"] if safe else []), "-i", str(clip.resolve()),
        "-filter_complex", filter_graph(cfg.layout, focus_x, safe),
        "-map", "[v]", "-map", "0:a?", *audio,
        *PLATFORM_VIDEO, "-preset", cfg.preset, "-crf", str(cfg.crf),
        *PLATFORM_AUDIO, "-movflags", "+faststart", str(out.resolve()),
        cwd=tmp, stderr=asyncio.subprocess.PIPE, **NO_WINDOW)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), ENCODE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"rendering took over {ENCODE_TIMEOUT // 60} minutes and was stopped"
    return proc.returncode == 0, err.decode(errors="replace").strip()


def needs_upgrade(clip: Path) -> bool:
    """Phone clips made before the upload-safe settings (level 4.0, colours left unknown)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=level,color_primaries", "-of", "json", str(clip)],
                       capture_output=True, text=True, **NO_WINDOW)
    try:
        s = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
    except ValueError:
        return False
    return bool(s) and (int(s.get("level") or 0) < 41 or s.get("color_primaries") in (None, "unknown"))


async def upgrade_old_clips(clips_dir: Path) -> int:
    """Re-encode older phone clips with the upload-safe settings (captions are already burned in,
    so this keeps them; high quality, so nothing visible is lost)."""
    done = 0
    for clip in sorted(clips_dir.glob("*/Phone clips/*.mp4")):
        if not await asyncio.to_thread(needs_upgrade, clip):
            continue
        work = clip.parent.parent / ".work"   # out of Phone clips while it's being made
        work.mkdir(parents=True, exist_ok=True)
        tmp = work / (clip.stem + ".rendering.mp4")  # a name the start-up recovery cleans up if interrupted
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip),
            *PLATFORM_VIDEO, "-preset", "medium", "-crf", "17", *PLATFORM_AUDIO, "-movflags", "+faststart", str(tmp),
            stderr=asyncio.subprocess.PIPE, **NO_WINDOW)
        _, err = await proc.communicate()
        if proc.returncode == 0 and probe_video_duration(tmp) >= probe_video_duration(clip) - 1:
            tmp.replace(clip)
            done += 1
        else:
            tmp.unlink(missing_ok=True)
            log.warning("couldn't upgrade %s: %s", clip.name, err.decode(errors="replace")[-200:])
    if done:
        log.info("🔧 updated %d older clip%s to upload-safe video settings", done, "" if done == 1 else "s")
    return done


def wrong_language(tr: Transcript, languages: list[str] | None) -> bool:
    """Only when Whisper is confident and heard enough speech to judge."""
    return bool(languages and tr.language and len(tr.words) >= 8
                and tr.language_probability >= 0.8 and tr.language not in languages)


def set_aside(clip: Path, meta_path: Path | None = None, dest: Path | None = None) -> Path:
    dest = dest or clip.parent / "other-languages"
    dest.mkdir(parents=True, exist_ok=True)
    for f in (clip, meta_path or clip.with_suffix(".json")):
        if f.exists():
            f.replace(dest / f.name)
    return dest


async def render_vertical(clip: Path, cfg: VerticalConfig, out: Path | None = None, **kw) -> Path | None:
    """Make the phone version of a clip (see _render_vertical). Its "current step" is always
    cleared afterwards, so the app never shows a finished or failed clip as still in progress."""
    try:
        return await _render_vertical(clip, cfg, out, **kw)
    finally:
        progress.done(clip.name)


async def _render_vertical(clip: Path, cfg: VerticalConfig, out: Path | None = None,
                          languages: list[str] | None = None, recent_dir: Path | None = None,
                          meta_path: Path | None = None, aside_dir: Path | None = None,
                          plan: Plan | None = None, words: list | None = None) -> Path | None:
    """Make the phone version of a clip and add the caption plan to its .json.

    With `plan` (and `words`) given, it re-renders with those captions as they are: no
    speech-to-text, no AI, no language check. That's how edits from the app are applied."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(max(1, cfg.max_parallel))
    async with _slots:  # transcription + encoding are CPU heavy; don't run 10 at once
        meta_path = meta_path or clip.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        length = await asyncio.to_thread(probe_duration, clip)

        edited = plan is not None
        if edited:
            words = words or []
        else:
            progress.step(clip.name, "Listening to what the streamer says")
            tr = await _transcribe_with_limit(clip, cfg.whisper_model) if cfg.speech_captions else Transcript([])
            words = tr.words
            if wrong_language(tr, languages):
                moved = set_aside(clip, meta_path, aside_dir)
                log.info("🌐 %s is in %s, not %s: moved to %s", clip.name, tr.language, "/".join(languages or []), moved)
                return None
            if cfg.ai_captions:
                progress.step(clip.name, "Writing the captions")
                plan = await claude_plan(clip, meta, words, length, cfg.ai_model,
                                         recent=load_recent(recent_dir or clip.parent))
            plan = plan or rule_plan(meta, words)
            remember_hook(recent_dir or clip.parent, plan.hook)
        log.info("✍️  %s: \"%s\" (%s, %s, %d words, %d beats)", clip.name, plan.hook, plan.mood,
                 plan.source, len(words), len(plan.beats))

        out = out or clip.with_name(clip.stem + "_vertical.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        progress.step(clip.name, "Rendering the video")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "captions.ass").write_text(
                build_ass(plan, words, length, cfg.layout, cfg.font), encoding="utf-8")
            want = probe_video_duration(clip) or length
            for safe in (False, True):
                ok, err = await _encode(clip, out, tmp, cfg, plan.crop_focus_x, safe)
                got = probe_video_duration(out) if ok else 0.0
                if ok and got >= want - 1.5:
                    break
                log.warning("%s: phone version came out %.1f s instead of %.1f s%s", clip.name, got, want,
                            ", rendering again in safe mode" if not safe else "")
            else:
                out.unlink(missing_ok=True)
                log.error("couldn't make a proper phone version of %s (%s). The original clip is fine.",
                          clip.name, err[-300:] or "video too short")
                return None

        meta["vertical"] = out.name
        meta["captions"] = {**asdict(plan), "transcript": " ".join(w.text for w in words),
                            "words": [[round(w.start, 2), round(w.end, 2), w.text] for w in words],
                            "layout": cfg.layout}
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("rendered %s", out.name)
        return out
