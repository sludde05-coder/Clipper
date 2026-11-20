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
from .director import hook_is_weak, Plan, claude_plan, rule_plan
from .transcribe import Transcript, transcribe
from .transcribe import Word
from .editors import default_trim, facecam_editor, post_editor, review_editor, trim_editor
from .proc import BACKGROUND, NO_WINDOW
from . import progress

log = logging.getLogger(__name__)
_slots: asyncio.Semaphore | None = None


def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, timeout=60, **NO_WINDOW)
    return float(r.stdout.strip() or 0)


def probe_video_duration(path: Path) -> float:
    """Length of the picture itself. The file's overall length can be longer when only the
    sound runs the full time, which is how a "1-second" clip can still claim to be 50 s."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=duration:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60, **NO_WINDOW)
    try:
        info = json.loads(r.stdout or "{}")
        streams = info.get("streams") or [{}]
        return float(streams[0].get("duration") or info.get("format", {}).get("duration") or 0)
    except (ValueError, TypeError):
        return 0.0


def probe_size(path: Path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60, **NO_WINDOW)
    try:
        w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
        return w, h
    except ValueError:
        return 1920, 1080


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


WEBCAM_LAYOUTS = ("facecam", "facecam_full")


def facecam_geometry(box: list, iw: int, ih: int, action_x: float, full: bool = False) -> dict:
    """Where to cut the webcam (top) and the gameplay (bottom) from a source frame of iw x ih.
    full=True: the bottom shows the whole stream screen, over a blurred copy of it."""
    fx, fy, fw, fh = box[0] * iw, box[1] * ih, box[2] * iw, box[3] * ih
    ht = min(800, max(480, _even(1080 * fh / max(fw, 1))))          # top part height on the 1080x1920 canvas
    a = 1080 / ht
    cw, ch = (fh * a, fh) if fw / max(fh, 1) > a else (fw, fw / a)   # cut the webcam to exactly that shape
    cx, cy = fx + (fw - cw) / 2, fy + (fh - ch) / 2
    hb = 1920 - ht
    b = 1080 / hb
    gw, gh = ih * b, ih
    if gw > iw:
        gw, gh = iw, iw / b
    gx = min(max(0.0, action_x * iw - gw / 2), iw - gw)
    gy = (ih - gh) / 2
    def fit(w, h, x, y):
        """Round to even pixels and keep the box inside the frame (ffmpeg refuses crops that stick out)."""
        w, h = min(_even(w), iw - iw % 2), min(_even(h), ih - ih % 2)
        x = min(max(0, _even(x) if x >= 1 else 0), iw - w)
        y = min(max(0, _even(y) if y >= 1 else 0), ih - h)
        return w, h, x, y

    if full:
        vh = min(hb, _even(1080 * ih / max(iw, 1)))            # the whole screen, full width
        top = ht + (hb - vh) // 2
        band = (hb - vh) // 2
        return {"ht": ht, "hb": hb, "vh": vh, "full": True, "cam": fit(cw, ch, cx, cy),
                # headline on the seam, spoken words in the blur under the screen, reactions over its middle
                "positions": (ht, top + vh + max(60, band // 2), top + vh // 2)}
    return {"ht": ht, "hb": hb,
            "cam": fit(cw, ch, cx, cy),
            "game": fit(gw, gh, gx, gy),
            # headline centred on the seam, spoken words low over the gameplay, reactions in its middle
            "positions": (ht, ht + int(hb * 0.70), ht + int(hb * 0.36))}


def resolve_layout(layout: str, facecam: list | None) -> str:
    if layout in ("auto", "facecam"):
        return "facecam" if facecam else "blur"
    if layout == "facecam_full":
        return "facecam_full" if facecam else "blur"
    return layout if layout in ("blur", "crop") else "blur"


def filter_graph(layout: str, focus_x: float, safe: bool = False, geo: dict | None = None) -> str:
    if layout == "facecam_full" and geo:
        src = "[0:v]setpts=N/FRAME_RATE/TB," if safe else "[0:v]"
        cw, ch, cx, cy = geo["cam"]
        hb = geo["hb"]
        return (f"{src}split=3[f][g][b];"
                f"[f]crop={cw}:{ch}:{cx}:{cy},scale=1080:{geo['ht']},setsar=1[top];"
                f"[b]scale=1080:{hb}:force_original_aspect_ratio=increase,crop=1080:{hb},"
                "gblur=sigma=40,eq=brightness=-0.12:saturation=1.2[bg];"
                f"[g]scale=1080:{geo['vh']},setsar=1[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[bot];"
                "[top][bot]vstack=inputs=2,ass=captions.ass[v]")
    if layout == "facecam" and geo:
        src = "[0:v]setpts=N/FRAME_RATE/TB," if safe else "[0:v]"
        cw, ch, cx, cy = geo["cam"]
        gw, gh, gx, gy = geo["game"]
        return (f"{src}split[f][g];"
                f"[f]crop={cw}:{ch}:{cx}:{cy},scale=1080:{geo['ht']},setsar=1[top];"
                f"[g]crop={gw}:{gh}:{gx}:{gy},scale=1080:{geo['hb']},setsar=1[bot];"
                f"[top][bot]vstack=inputs=2,ass=captions.ass[v]")
    return _filter_graph(layout, focus_x, safe)


def with_headline(graph: str, overlay: str | None) -> str:
    """Put the headline picture (ffmpeg input 1) over the finished frame."""
    if not overlay:
        return graph
    assert graph.endswith("[v]")
    return graph[:-3] + "[base];" + overlay


def write_captions(tmp: Path, plan: Plan, words: list, length: float, layout: str, cfg: VerticalConfig,
                   geo: dict | None, fade: bool = True) -> tuple[list[str], str | None]:
    """Write captions.ass into tmp, and the headline as a picture when it can be drawn (so it can end
    in a colour emoji). Returns the extra ffmpeg inputs and the overlay step for with_headline()."""
    from .captions import POSITIONS
    from .headline import render
    positions = geo["positions"] if geo else POSITIONS.get(layout, POSITIONS["blur"])
    anchor = 5 if geo else 2
    size = render(plan.hook, tmp / "headline.png") if plan.hook.strip() else None
    (tmp / "captions.ass").write_text(
        build_ass(plan, words, length, layout, cfg.font, positions=positions if geo else None,
                  hook_anchor=anchor, draw_hook=size is None), encoding="utf-8")
    if size is None:
        return [], None
    w, h = size
    y = positions[0] - (h if anchor == 2 else h // 2)
    fade_in = ",fade=in:st=0:d=0.25:alpha=1" if fade else ""
    overlay = (f"[1:v]format=rgba{fade_in}[hl];"
               f"[base][hl]overlay=x={(1080 - w) // 2}:y={max(0, y)}:shortest=1:format=auto[v]")
    return ["-loop", "1", "-framerate", "30", "-i", "headline.png"], overlay


def _filter_graph(layout: str, focus_x: float, safe: bool = False) -> str:
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
                  safe: bool, layout: str | None = None, geo: dict | None = None,
                  extra: tuple[list[str], str | None] = ([], None)) -> tuple[bool, str]:
    audio = ["-af", "asetpts=N/SR/TB"] if safe else []
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        *(["-fflags", "+genpts"] if safe else []), "-i", str(clip.resolve()), *extra[0],
        "-filter_complex", with_headline(filter_graph(layout or cfg.layout, focus_x, safe, geo), extra[1]),
        "-map", "[v]", "-map", "0:a?", *audio,
        *PLATFORM_VIDEO, "-preset", cfg.preset, "-crf", str(cfg.crf),
        *PLATFORM_AUDIO, "-movflags", "+faststart", str(out.resolve()),
        cwd=tmp, stderr=asyncio.subprocess.PIPE, **BACKGROUND)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), ENCODE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"rendering took over {ENCODE_TIMEOUT // 60} minutes and was stopped"
    except asyncio.CancelledError:      # stopped from the app: don't leave ffmpeg running
        proc.kill()
        raise
    return proc.returncode == 0, err.decode(errors="replace").strip()


AI_STAGE_LIMIT = 240   # seconds one AI editor may take in all (incl. a retry); then the clip goes on without it


async def _safe(job, limit: float | None = None):
    """Run one editor with a time limit; if it fails or takes too long, carry on without it."""
    limit = limit or AI_STAGE_LIMIT
    try:
        return await asyncio.wait_for(job, limit)
    except asyncio.TimeoutError:
        log.warning("an AI editor took over %d minutes; carrying on without it", limit // 60)
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("an AI editor failed (%s: %s); carrying on without it", type(e).__name__, e)
        return None


async def _render_once(clip: Path, out: Path, plan: Plan, words: list, length: float, layout: str,
                       cfg: VerticalConfig) -> bool:
    geo = None
    if layout in WEBCAM_LAYOUTS and plan.facecam:
        iw, ih = await asyncio.to_thread(probe_size, clip)
        geo = facecam_geometry(plan.facecam, iw, ih, plan.crop_focus_x, full=layout == "facecam_full")
    with tempfile.TemporaryDirectory() as tmp:
        extra = write_captions(Path(tmp), plan, words, length, layout, cfg, geo)
        want = probe_video_duration(clip) or length
        for safe in (False, True):
            ok, err = await _encode(clip, out, tmp, cfg, plan.crop_focus_x, safe, layout=layout, geo=geo, extra=extra)
            got = probe_video_duration(out) if ok else 0.0
            if ok and got >= want - 1.5:
                return True
            log.warning("%s: phone version came out %.1f s instead of %.1f s%s", clip.name, got, want,
                        ", rendering again in safe mode" if not safe else "")
    out.unlink(missing_ok=True)
    log.error("couldn't make a proper phone version of %s (%s). The original clip is fine.",
              clip.name, err[-300:] or "video too short")
    return False


async def _cut(clip: Path, start: float, end: float) -> bool:
    """Cut the recording down to start..end (frame-accurate), in place."""
    tmp = clip.with_name(clip.stem + ".rendering.mp4")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", str(clip),
        "-t", f"{end - start:.3f}", "-map", "0:v?", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp),
        stderr=asyncio.subprocess.PIPE, **BACKGROUND)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), ENCODE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        err = b"cutting took too long"
    except asyncio.CancelledError:
        proc.kill()
        raise
    if proc.returncode != 0 or probe_video_duration(tmp) < (end - start) * 0.8:
        tmp.unlink(missing_ok=True)
        log.warning("couldn't cut %s to the moment (%s); keeping the whole recording", clip.name,
                    err.decode(errors="replace")[-200:])
        return False
    tmp.replace(clip)
    return True


def shift_words(words: list, start: float, end: float) -> list:
    return [Word(w.start - start, w.end - start, w.text) for w in words if w.end > start and w.start < end]


def shift_meta(meta: dict, start: float, end: float) -> dict:
    meta = dict(meta)
    if "explosion_offset" in meta:
        meta["explosion_offset"] = round(float(meta["explosion_offset"]) - start, 1)
    if meta.get("chat_timeline"):
        meta["chat_timeline"] = [[round(float(t) - start, 1), u, m] for t, u, m in meta["chat_timeline"]
                                 if start <= float(t) <= end]
    return meta


def needs_upgrade(clip: Path) -> bool:
    """Phone clips made before the upload-safe settings (level 4.0, colours left unknown)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=level,color_primaries", "-of", "json", str(clip)],
                       capture_output=True, text=True, timeout=60, **NO_WINDOW)
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
            stderr=asyncio.subprocess.PIPE, **BACKGROUND)
        _, err = await proc.communicate()
        if proc.returncode == 0 and probe_video_duration(tmp) >= probe_video_duration(clip) - 1:
            try:
                tmp.replace(clip)
                done += 1
            except OSError:              # the clip is open somewhere (Windows locks it): upgrade it next time
                tmp.unlink(missing_ok=True)
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
    cleared afterwards, so the app never shows a finished or failed clip as still in progress.
    The work runs as its own task, so Delete in the app can stop it (then this returns None)."""
    task = asyncio.ensure_future(_render_vertical(clip, cfg, out, **kw))
    progress.attach(clip.name, task)
    try:
        return await task
    except asyncio.CancelledError:
        if progress.was_stopped(clip.name) and not _current_cancelling():
            log.info("⏹ stopped making %s", clip.name)
            return None
        raise
    finally:
        progress.done(clip.name)


def _current_cancelling() -> bool:
    """Is the task running this code itself being cancelled (e.g. the app is closing)?"""
    me = asyncio.current_task()
    return bool(me and getattr(me, "cancelling", lambda: 0)())


async def _render_vertical(clip: Path, cfg: VerticalConfig, out: Path | None = None,
                          languages: list[str] | None = None, recent_dir: Path | None = None,
                          meta_path: Path | None = None, aside_dir: Path | None = None,
                          plan: Plan | None = None, words: list | None = None,
                          trim_window: tuple[float, float] | None = None) -> Path | None:
    """Make the phone version of a clip and add the caption plan to its .json.

    For a new clip this runs the AI editing team (see editors.py): trim + webcam editors side by
    side, then the clip is cut to the moment, caption + post editors side by side, the render, and
    a final review that can ask for one fix. trim_window = (seconds before, after) the explosion to
    keep when the trim editor isn't available.

    With `plan` (and `words`) given, it re-renders with those captions as they are: no
    speech-to-text, no AI, no language check. That's how edits from the app are applied."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(max(1, cfg.max_parallel))
    progress.step(clip.name, progress.WAITING)
    async with _slots:  # transcription + encoding are CPU heavy; don't run 10 at once
        meta_path = meta_path or clip.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        length = await asyncio.to_thread(probe_duration, clip)

        edited = plan is not None
        use_ai = cfg.ai_captions and cfg.ai_editors
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
            # 1 + 2: trim and webcam editors, side by side
            trim, face = None, None
            if use_ai:
                progress.step(clip.name, "Trim and webcam editors are watching the clip")
                trim, face = await asyncio.gather(_safe(trim_editor(clip, meta, words, length, cfg.ai_model)),
                                                  _safe(facecam_editor(clip, length, cfg.ai_model)))  # time-limited in _safe
            if trim is None and trim_window:
                offset = float(meta.get("explosion_offset", length - trim_window[1]))
                trim = default_trim(offset, length, *trim_window)
            if trim is not None and (trim.start > 0.05 or trim.end < length - 0.05):
                progress.step(clip.name, "Cutting to the moment")
                if await _cut(clip, trim.start, trim.end):
                    words = shift_words(words, trim.start, trim.end)
                    meta = shift_meta(meta, trim.start, trim.end)
                    length = await asyncio.to_thread(probe_duration, clip)
                    log.info("✂️  %s: kept %.0f-%.0f s (%s)", clip.name, trim.start, trim.end, trim.why or trim.source)
            if trim is not None:
                meta["trim"] = {"start": trim.start, "end": trim.end, "why": trim.why, "by": trim.source}
            # 3 + 4: caption and post editors, side by side
            post = None
            if cfg.ai_captions:
                progress.step(clip.name, "Caption and post editors are writing" if use_ai else "Writing the captions")
                captions_job = claude_plan(clip, meta, words, length, cfg.ai_model,
                                           recent=load_recent(recent_dir or clip.parent))
                if use_ai:
                    plan, post = await asyncio.gather(_safe(captions_job), _safe(post_editor(
                        meta, "", trim.why if trim else "", words, cfg.ai_model)))
                else:
                    plan = await _safe(captions_job)
            plan = plan or rule_plan(meta, words)
            if face:
                plan.facecam, plan.crop_focus_x = face[0], face[1]
            if post:
                meta["ai_post"] = post
            remember_hook(recent_dir or clip.parent, plan.hook)
        log.info("✍️  %s: \"%s\" (%s, %s, %d words, %d beats)", clip.name, plan.hook, plan.mood,
                 plan.source, len(words), len(plan.beats))

        out = out or clip.with_name(clip.stem + "_vertical.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        layout = resolve_layout(cfg.layout, plan.facecam)
        progress.step(clip.name, "Rendering the video")
        if not await _render_once(clip, out, plan, words, length, layout, cfg):
            return None

        # 5: the review editor looks at the finished video and may ask for one fix
        if not edited and use_ai and plan.source == "claude":
            progress.step(clip.name, "Review editor is checking the result")
            review = await _safe(review_editor(out, length, plan.hook, layout, plan.beats, cfg.ai_model))
            if review is not None:
                meta["review"] = review
                changed = []
                if review["new_hook"] and not hook_is_weak(review["new_hook"], []) and review["new_hook"] != plan.hook:
                    plan.hook = review["new_hook"]
                    changed.append("headline")
                if review["layout"] in ("blur", "crop") and review["layout"] != layout:
                    layout = review["layout"]
                    changed.append("layout")
                if review["drop_beats"] and plan.beats:
                    plan.beats = []
                    changed.append("reaction captions")
                if changed:
                    log.info("🔁 review editor: fixing the %s (%s)", " and ".join(changed), "; ".join(review["issues"])[:160])
                    progress.step(clip.name, "Applying the review editor's fixes")
                    if not await _render_once(clip, out, plan, words, length, layout, cfg):
                        return None
                else:
                    log.info("✅ review editor: looks good")

        meta["vertical"] = out.name
        meta["captions"] = {**asdict(plan), "transcript": " ".join(w.text for w in words),
                            "words": [[round(w.start, 2), round(w.end, 2), w.text] for w in words],
                            "layout": layout}
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("rendered %s", out.name)
        return out
