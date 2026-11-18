"""The Clipper desktop app: a window on the PC for everything the clipper does.

`python -m clipper app` (what Clipper.bat and the desktop icon run) starts a small server on
this PC only (127.0.0.1) and opens it in an app window (Microsoft Edge "app mode" on Windows).
From there you start and stop clipping, browse every streamer's clips, edit captions and
re-render them, link the posting platforms, change settings and post the clips you tick.

Clipping keeps running when the window is closed; the Quit button stops everything.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from collections import deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiohttp import web

from . import naming, progress
from .config import Config, load_config
from .director import MOODS, Beat, Plan
from .models import parse_target
from .orchestrator import Orchestrator
from .poster import TARGETS, captions_for, find_metadata, show_file
from .proc import NO_WINDOW
from .setup_wizard import check_anthropic, check_kick, check_twitch, check_youtube, ensure_config, set_value
from .transcribe import Word
from .vertical import probe_duration, render_vertical

log = logging.getLogger(__name__)
UI_DIR = Path(__file__).parent / "app_ui"
PORT = 8766
NAME_RE = re.compile(r"^(?P<streamer>.+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})_(?P<n>\d+)$")
SIGN_IN = {"tiktok": "https://www.tiktok.com/login", "youtube": "https://studio.youtube.com",
           "instagram": "https://www.instagram.com/accounts/login/"}
DELETED = "Deleted clips"

# What the Settings page shows: (section, key, label, kind, help, options)
SETTINGS = [
    ("discovery", "game", "Game to clip", "text", "Twitch/Kick category name, e.g. Grand Theft Auto VI", None),
    ("discovery", "top_n", "How many streams to track", "number", "The biggest live streams of the game", None),
    ("discovery", "min_viewers", "Minimum viewers", "number", "Smaller streams are skipped", None),
    ("discovery", "platforms", "Find streams on", "multi", "", ["twitch", "youtube", "kick"]),
    ("discovery", "languages", "Language", "language", "", None),
    ("discovery", "always_track", "Always clip these streamers", "lines",
     "One per line, e.g. twitch:kaicenat, kick:adinross or a YouTube live link", None),
    ("clips", "pre_roll", "Seconds before chat explodes", "number", "", None),
    ("clips", "post_roll", "Seconds after", "number", "", None),
    ("clips", "quality", "Video quality", "select", "Lower it if your internet can't keep up", ["best", "1080p60", "720p60", "720p", "480p"]),
    ("clips", "keep_originals", "Keep 16:9 originals", "bool", "Otherwise they're deleted once a clip is posted", None),
    ("detector", "multiplier", "How big a chat explosion must be", "number", "x normal chat speed (higher = fewer clips)", None),
    ("detector", "min_rate", "Minimum chat speed", "number", "Messages per second (stops tiny chats from clipping)", None),
    ("detector", "cooldown", "Seconds between clips of one streamer", "number", "", None),
    ("vertical", "layout", "Phone clip layout", "select", "blur: whole picture over a blurred background. crop: fills the screen", ["blur", "crop"]),
    ("vertical", "ai_captions", "AI captions", "bool", "Claude writes the headline and reaction captions", None),
    ("vertical", "ai_model", "AI model", "select", "Haiku costs about 0.1 cent per clip, Opus about 3-5 cents",
     ["claude-haiku-5-5", "claude-opus-5-5"]),
    ("vertical", "speech_captions", "Word-by-word captions", "bool", "What the streamer says, from speech-to-text", None),
    ("vertical", "whisper_model", "Speech-to-text model", "select", "base is faster, small is more accurate",
     ["base", "small", "medium"]),
    ("twitch", "client_id", "Twitch Client ID", "text", "", None),
    ("twitch", "client_secret", "Twitch Client Secret", "secret", "", None),
    ("youtube", "api_key", "YouTube API key", "secret", "", None),
    ("kick", "client_id", "Kick Client ID", "text", "", None),
    ("kick", "client_secret", "Kick Client Secret", "secret", "", None),
    ("anthropic", "api_key", "Anthropic API key (AI captions)", "secret", "", None),
    ("phone", "enabled", "Phone app", "bool", "Lets your phone post clips from the POST folder", None),
]
KEY_TESTS = {"twitch": (check_twitch, ["client_id", "client_secret"]), "youtube": (check_youtube, ["api_key"]),
             "kick": (check_kick, ["client_id", "client_secret"]), "anthropic": (check_anthropic, ["api_key"])}


class LogBuffer(logging.Handler):
    """Keeps recent log lines for the app's activity panel."""

    def __init__(self, size: int = 600):
        super().__init__(logging.INFO)
        self.lines: deque[dict] = deque(maxlen=size)
        self.next_id = 1

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if msg.startswith("status\n"):
            return  # the app shows the status table itself
        self.lines.append({"id": self.next_id, "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                           "level": record.levelname.lower(), "text": msg})
        self.next_id += 1


class ClipperApp:
    def __init__(self, config_path: str = "config.toml"):
        self.config_path = config_path
        ensure_config(Path(config_path))
        self.cfg = load_config(config_path)
        self.logs = LogBuffer()
        logging.getLogger().addHandler(self.logs)
        self.orch: Orchestrator | None = None
        self.clip_task: asyncio.Task | None = None
        self.mode = ""
        self.stopping = False
        self.jobs: dict[str, dict] = {}
        self.last_seen = time.time()
        self.phone = None
        self.quit_event = asyncio.Event()
        self.needs_restart = False
        self._autoposter = None

    # ------------------------------------------------------------ paths

    @property
    def clips_dir(self) -> Path:
        return Path(self.cfg.clips.output_dir)

    def _clip(self, cid: str) -> Path:
        """A phone clip by id (its path under the clips folder); refuses anything outside it."""
        p = (self.clips_dir / cid).resolve()
        root = self.clips_dir.resolve()
        if root not in p.parents or p.suffix.lower() != ".mp4" or p.parent.name != naming.PHONE or not p.is_file():
            raise web.HTTPNotFound(text="clip not found")
        return p

    def _id(self, clip: Path) -> str:
        return clip.resolve().relative_to(self.clips_dir.resolve()).as_posix()

    @staticmethod
    def _details(clip: Path) -> Path:
        return clip.parent.parent / naming.DETAILS / (clip.stem + ".json")

    def _meta(self, clip: Path) -> dict:
        p = self._details(clip)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return find_metadata(clip, self.clips_dir)

    def _save_meta(self, clip: Path, meta: dict) -> None:
        p = self._details(clip)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    def _platforms(self) -> list[str]:
        return [k for k in self.cfg.post.platforms if k in TARGETS]

    # ------------------------------------------------------------ guard

    @web.middleware
    async def guard(self, request: web.Request, handler):
        # Only this PC, and no other website can make the app do things (DNS rebinding / CSRF).
        host = (request.host or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return web.Response(status=403, text="forbidden")
        if request.method != "GET" and request.headers.get("X-Clipper") != "1":
            return web.Response(status=403, text="forbidden")
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("app request failed: %s: %s: %s", request.path, type(e).__name__, e, exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    # ------------------------------------------------------------ basics

    async def index(self, request):
        return web.FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})

    async def icon(self, request):
        return web.FileResponse(UI_DIR / "icon.png")

    async def ping(self, request):
        self.last_seen = time.time()
        return web.json_response({"app": "clipper"})

    async def state(self, request):
        self.last_seen = time.time()
        running = self.clip_task is not None and not self.clip_task.done()
        return web.json_response({
            "running": running, "stopping": self.stopping, "mode": self.mode,
            "game": self.cfg.discovery.game, "rows": self.orch.status_rows() if (self.orch and running) else [],
            "multiplier": self.cfg.detector.multiplier, "min_rate": self.cfg.detector.min_rate,
            "phone_url": self.phone.phone_url if self.phone else "", "needs_restart": self.needs_restart and running,
            "jobs": {k: v["state"] for k, v in self.jobs.items() if v["state"] == "running"},
            "platforms": [{"key": k, "name": TARGETS[k].name} for k in self._platforms()],
            "autofill": self.cfg.post.autofill,
            "autosubmit": self.cfg.post.autofill and self.cfg.post.autosubmit,
            "pause_between_clips": self.cfg.post.pause_between_clips,
        })

    async def logs_since(self, request):
        after = int(request.query.get("after", 0))
        return web.json_response({"lines": [line for line in self.logs.lines if line["id"] > after]})

    # ------------------------------------------------------------ clipping

    async def start_clipping(self, request):
        if self.clip_task and not self.clip_task.done():
            return web.json_response({"ok": True})
        body = await request.json()
        mode = body.get("mode", "top")
        self.cfg = load_config(self.config_path)
        self.needs_restart = False
        cfg = self.cfg
        if mode == "test":
            game = (body.get("game") or "Grand Theft Auto V").strip()
            from .__main__ import ALIASES
            cfg = replace(cfg, discovery=replace(cfg.discovery, game=game,
                                                 search_terms=[game, *ALIASES.get(game.lower(), [])]))
        self.orch = Orchestrator(cfg, self.config_path, start_phone=False, log_status=False)
        if mode == "watch":
            targets = [t for t in re.split(r"[\s,]+", body.get("targets", "")) if t]
            try:
                streams = [parse_target(t) for t in targets]
            except ValueError as e:
                return web.json_response({"error": str(e)}, status=400)
            if not streams:
                return web.json_response({"error": "Type at least one streamer"}, status=400)
            self.clip_task = asyncio.create_task(self.orch.run_fixed(streams))
            self.mode = "Clipping " + ", ".join(s.key for s in streams)
        else:
            self.clip_task = asyncio.create_task(self.orch.run_discovery())
            self.mode = f"Clipping the top {cfg.discovery.top_n} {cfg.discovery.game} streams"
        log.info("▶  %s", self.mode)
        return web.json_response({"ok": True})

    async def stop_clipping(self, request=None):
        if not (self.clip_task and not self.clip_task.done()):
            return web.json_response({"ok": True})
        self.stopping = True
        log.info("⏹  Stopping: finishing clips that are in progress…")
        try:
            self.clip_task.cancel()
            await asyncio.gather(self.clip_task, return_exceptions=True)
            if self.orch:
                await self.orch.stop_all()
        finally:
            self.stopping = False
            self.mode = ""
        log.info("⏹  Clipping stopped")
        return web.json_response({"ok": True})

    # ------------------------------------------------------------ clips

    def _list_clips(self) -> list[Path]:
        if not self.clips_dir.exists():
            return []
        out = []
        for streamer in self.clips_dir.iterdir():
            if streamer.is_dir() and streamer.name != DELETED and not streamer.name.startswith("."):
                out += [p for p in (streamer / naming.PHONE).glob("*.mp4") if not p.name.endswith(".rendering.mp4")]

        def newest(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0
        return sorted(out, key=newest, reverse=True)

    def _summary(self, clip: Path) -> dict:
        meta = self._meta(clip)
        m = NAME_RE.match(clip.stem)
        cid = self._id(clip)
        posted = meta.get("posted") or {}
        return {
            "id": cid, "name": clip.stem, "streamer": clip.parent.parent.name,
            "date": m["date"] if m else "", "time": m["time"].replace("-", ":") if m else "",
            "number": int(m["n"]) if m else 0,
            "hook": (meta.get("captions") or {}).get("hook", ""),
            "source": meta.get("platform", ""), "mood": (meta.get("captions") or {}).get("mood", ""),
            "posted": {k: bool(posted.get(k)) for k in self._platforms()},
            "added": clip.stat().st_mtime,
            "video": f"/media?id={quote(cid)}&v={int(clip.stat().st_mtime)}",
            "thumb": f"/thumb?id={quote(cid)}&v={int(clip.stat().st_mtime)}",
            "rendering": self.jobs.get(cid, {}).get("state") == "running",
        }

    async def clips(self, request):
        clips = []
        for c in self._list_clips():
            try:
                clips.append(self._summary(c))
            except (OSError, ValueError) as e:  # e.g. a file that's being moved right now
                log.debug("skipping %s in the clip list: %s", c, e)
        streamers: dict[str, dict] = {}
        for c in clips:
            s = streamers.setdefault(c["streamer"], {"name": c["streamer"], "count": 0, "to_post": 0})
            s["count"] += 1
            s["to_post"] += not all(c["posted"].values()) if c["posted"] else 1
        return web.json_response({"clips": clips, "streamers": sorted(streamers.values(), key=lambda s: s["name"].lower()),
                                  **self._side_lists()})

    def _side_lists(self) -> dict:
        """Clips that aren't in Phone clips (yet): being made, failed, or set aside for another language."""
        making, failed, other = [], [], []
        if self.clips_dir.exists():
            for streamer in self.clips_dir.iterdir():
                if not streamer.is_dir() or streamer.name == DELETED or streamer.name.startswith("."):
                    continue
                for folder, out in ((naming.WORK, making), (naming.NOT_CONVERTED, failed), (naming.OTHER_LANGUAGES, other)):
                    for p in (streamer / folder).glob("*.mp4"):
                        if p.name.endswith((".phone.mp4", ".rendering.mp4")):
                            continue
                        m = NAME_RE.match(p.stem)
                        now = progress.get(p.name) if folder == naming.WORK else None
                        out.append({"streamer": streamer.name, "name": p.stem,
                                    "step": now[0] if now else "", "minutes": int((time.time() - now[1]) // 60) if now else 0,
                                    "date": m["date"] if m else "", "time": m["time"].replace("-", ":") if m else "",
                                    "number": int(m["n"]) if m else 0})
        return {"making": making, "failed": failed, "other_languages": other}

    async def retry_failed(self, request):
        """Try making the phone clips again for clips in Not converted."""
        from .session import finish_clip
        body = await request.json()
        wanted = {(x.get("streamer"), x.get("name")) for x in body.get("clips", [])}
        jobs = []
        for item in self._side_lists()["failed"]:
            if wanted and (item["streamer"], item["name"]) not in wanted:
                continue
            streamer = self.clips_dir / item["streamer"]
            work = naming.move_into(streamer / naming.NOT_CONVERTED / f"{item['name']}.mp4", streamer / naming.WORK)
            jobs.append(work)

        async def run():
            for work in jobs:
                details = naming.details_path(work)
                try:
                    phone = await finish_clip(work, details, self.cfg)
                    log.info("🔁 %s: %s", work.name, "phone clip made" if phone else "failed again")
                except Exception as e:  # noqa: BLE001
                    log.error("couldn't make %s: %s", work.name, e)

        if jobs:
            asyncio.create_task(run())
        return web.json_response({"ok": True, "retrying": len(jobs)})

    async def clip_detail(self, request):
        clip = self._clip(request.query.get("id", ""))
        meta = self._meta(clip)
        cap = meta.get("captions") or {}
        words = cap.get("words")
        return web.json_response({
            **self._summary(clip),
            "title": meta.get("title", ""), "url": meta.get("url", ""), "streamer_name": meta.get("name", ""),
            "hook": cap.get("hook", ""), "mood": cap.get("mood", "hype"), "moods": MOODS,
            "layout": cap.get("layout", self.cfg.vertical.layout),
            "beats": cap.get("beats", []),
            "words_text": " ".join(w[2] for w in words) if words else cap.get("transcript", ""),
            "has_word_timings": bool(words), "speech_on": bool(words or cap.get("transcript")),
            "explosion_offset": meta.get("explosion_offset"),
            "length": round(probe_duration(clip), 1),
            "can_rerender": naming.source_for(clip) is not None,
            "post": captions_for(meta, clip, self.cfg.post),
            "post_edited": sorted((meta.get("post") or {}).keys()),
            "posted_at": meta.get("posted") or {},
            "accounts": {k: getattr(self.cfg.post, f"{k}_account", "") for k in self._platforms()},
        })

    async def save_post(self, request):
        body = await request.json()
        clip = self._clip(body.get("id", ""))
        meta = self._meta(clip)
        post = meta.get("post") or {}
        for key, fields in (body.get("post") or {}).items():
            if key in TARGETS and isinstance(fields, dict):
                post[key] = {k: str(v) for k, v in fields.items() if k in ("caption", "title", "description")}
        if body.get("reset"):
            post.pop(body["reset"], None)
        meta["post"] = post
        self._save_meta(clip, meta)
        return web.json_response({"ok": True, "post": captions_for(meta, clip, self.cfg.post)})

    async def rerender(self, request):
        body = await request.json()
        clip = self._clip(body.get("id", ""))
        cid = self._id(clip)
        source = naming.source_for(clip)
        if not source:
            return web.json_response({"error": "The original of this clip is gone, so its captions can't be "
                                               "re-rendered. You can still edit the post captions."}, status=400)
        if self.jobs.get(cid, {}).get("state") == "running":
            return web.json_response({"error": "Already rendering"}, status=409)
        self.jobs[cid] = {"state": "running", "error": ""}
        asyncio.create_task(self._do_rerender(cid, clip, source, body))
        return web.json_response({"ok": True})

    async def _do_rerender(self, cid: str, clip: Path, source: Path, body: dict) -> None:
        try:
            meta = self._meta(clip)
            cap = meta.get("captions") or {}
            length = probe_duration(source)
            words = self._edited_words(cap, body, length)
            if words is None:  # older clip without word timings: listen again
                from .transcribe import transcribe
                words = (await asyncio.to_thread(transcribe, source, self.cfg.vertical.whisper_model)).words
            beats = [Beat(float(b["t"]), str(b["text"]).strip()) for b in body.get("beats", [])
                     if str(b.get("text", "")).strip() and 0 <= float(b.get("t", -1)) < length]
            mood = body.get("mood") if body.get("mood") in MOODS else cap.get("mood", "hype")
            plan = Plan(hook=str(body.get("hook", "")).strip(), mood=mood, beats=beats,
                        emphasis=cap.get("emphasis", []), crop_focus_x=float(cap.get("crop_focus_x", 0.5)),
                        post_caption=cap.get("post_caption", ""), source="edited")
            layout = body.get("layout") if body.get("layout") in ("blur", "crop") else self.cfg.vertical.layout
            vcfg = replace(self.cfg.vertical, layout=layout)
            work = clip.parent.parent / naming.WORK
            work.mkdir(parents=True, exist_ok=True)
            tmp_out = work / (clip.stem + ".rendering.mp4")  # out of Phone clips until it's finished
            details = self._details(clip)
            done = await render_vertical(source, vcfg, out=tmp_out, meta_path=details, plan=plan, words=words)
            if not done:
                raise RuntimeError("rendering failed (see the activity log)")
            tmp_out.replace(clip)
            meta = self._meta(clip)
            meta["vertical"] = clip.name
            self._save_meta(clip, meta)
            log.info("✏️  re-rendered %s with your edits", clip.name)
            self.jobs[cid] = {"state": "done", "error": ""}
        except Exception as e:  # noqa: BLE001
            (clip.parent.parent / naming.WORK / (clip.stem + ".rendering.mp4")).unlink(missing_ok=True)
            log.error("couldn't re-render %s: %s", clip.name, e)
            self.jobs[cid] = {"state": "error", "error": str(e)}

    @staticmethod
    def _edited_words(cap: dict, body: dict, length: float) -> list[Word] | None:
        """Apply edited spoken text to the word timings: same number of words keeps every timing,
        otherwise the new words are spread over the same stretch of time."""
        if not body.get("speech_on", True):
            return []
        old = [Word(float(s), float(e), t) for s, e, t in (cap.get("words") or [])]
        text = str(body.get("words_text", "")).split()
        if not old:
            return None if text else []
        if not text:
            return []
        if len(text) == len(old):
            return [Word(w.start, w.end, t) for w, t in zip(old, text)]
        start, end = old[0].start, old[-1].end
        step = (end - start) / len(text)
        return [Word(start + i * step, start + (i + 1) * step - 0.02, t) for i, t in enumerate(text)]

    async def job(self, request):
        return web.json_response(self.jobs.get(request.query.get("id", ""), {"state": "none", "error": ""}))

    def _to_bin(self, clip: Path) -> None:
        """Move a clip (phone video, details, hidden original) to clips/Deleted clips/<Streamer>/."""
        bin_dir = self.clips_dir / DELETED / clip.parent.parent.name
        bin_dir.mkdir(parents=True, exist_ok=True)
        source = naming.source_for(clip)
        for f, name in ((clip, clip.name), (self._details(clip), clip.stem + ".json"),
                        (source, clip.stem + "_original.mp4")):
            if f and f.exists():
                f.replace(bin_dir / name)

    async def delete_clip(self, request):
        body = await request.json()
        ids = body.get("ids") or ([body["id"]] if body.get("id") else [])
        done = 0
        for cid in ids:
            try:
                self._to_bin(self._clip(cid))
                done += 1
            except web.HTTPNotFound:
                continue
        log.info("🗑  moved %d clip%s to %s", done, "" if done == 1 else "s", DELETED)
        return web.json_response({"ok": True, "deleted": done})

    # ------------------------------------------------------------ deleted clips

    def _bin_clip(self, cid: str) -> Path:
        """A clip in Deleted clips by id; refuses anything else."""
        p = (self.clips_dir / cid).resolve()
        bin_root = (self.clips_dir / DELETED).resolve()
        if (p.parent.parent != bin_root or p.suffix.lower() != ".mp4" or p.stem.endswith("_original")
                or not p.is_file()):
            raise web.HTTPNotFound(text="clip not found")
        return p

    def _bin_files(self, clip: Path) -> list[Path]:
        return [f for f in (clip, clip.with_suffix(".json"), clip.with_name(clip.stem + "_original.mp4")) if f.exists()]

    async def deleted(self, request):
        root = self.clips_dir / DELETED
        items = []
        if root.exists():
            for p in sorted(root.glob("*/*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
                if p.stem.endswith("_original"):
                    continue
                cid = self._id(p)
                m = NAME_RE.match(p.stem)
                try:
                    hook = (json.loads(p.with_suffix(".json").read_text(encoding="utf-8")).get("captions") or {}).get("hook", "")
                except (OSError, ValueError):
                    hook = ""
                items.append({"id": cid, "name": p.stem, "streamer": p.parent.name, "hook": hook,
                              "date": m["date"] if m else "", "time": m["time"].replace("-", ":") if m else "",
                              "number": int(m["n"]) if m else 0,
                              "size_mb": round(sum(f.stat().st_size for f in self._bin_files(p)) / 1e6, 1),
                              "thumb": f"/thumb?id={quote(cid)}&deleted=1&v={int(p.stat().st_mtime)}"})
        return web.json_response({"clips": items, "total_mb": round(sum(i["size_mb"] for i in items), 1)})

    async def restore(self, request):
        body = await request.json()
        done = 0
        for cid in body.get("ids", []):
            try:
                clip = self._bin_clip(cid)
            except web.HTTPNotFound:
                continue
            streamer = self.clips_dir / clip.parent.name
            for f, dest in ((clip, streamer / naming.PHONE / clip.name),
                            (clip.with_suffix(".json"), streamer / naming.DETAILS / (clip.stem + ".json")),
                            (clip.with_name(clip.stem + "_original.mp4"), streamer / naming.SOURCE / clip.name)):
                if f.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    f.replace(dest)
            done += 1
        log.info("↩  restored %d clip%s", done, "" if done == 1 else "s")
        return web.json_response({"ok": True, "restored": done})

    async def purge(self, request):
        """Delete clips in Deleted clips for good (all of them with {"all": true})."""
        body = await request.json()
        root = self.clips_dir / DELETED
        if body.get("all"):
            clips = [p for p in root.glob("*/*.mp4") if not p.stem.endswith("_original")] if root.exists() else []
        else:
            clips = []
            for cid in body.get("ids", []):
                try:
                    clips.append(self._bin_clip(cid))
                except web.HTTPNotFound:
                    continue
        freed = 0
        for clip in clips:
            for f in self._bin_files(clip):
                freed += f.stat().st_size
                f.unlink()
            (self.clips_dir / ".thumbs" / (clip.parent.name + "__" + clip.stem + ".jpg")).unlink(missing_ok=True)
        if root.exists():
            for d in root.iterdir():
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
        log.info("🗑  deleted %d clip%s for good (%.0f MB freed)", len(clips), "" if len(clips) == 1 else "s", freed / 1e6)
        return web.json_response({"ok": True, "deleted": len(clips), "freed_mb": round(freed / 1e6, 1)})

    async def mark_posted(self, request):
        body = await request.json()
        clip = self._clip(body.get("id", ""))
        platform = body.get("platform")
        if platform not in TARGETS:
            raise web.HTTPBadRequest(text="unknown platform")
        meta = self._meta(clip)
        posted = meta.get("posted") or {}
        if body.get("posted", True):
            posted[platform] = datetime.now().isoformat(timespec="seconds")
        else:
            posted.pop(platform, None)
        meta["posted"] = posted
        self._save_meta(clip, meta)
        return web.json_response({"ok": True})

    async def finish_clip(self, request):
        """Called when the Post walkthrough is done with a clip: the hidden original goes once it's posted."""
        body = await request.json()
        clip = self._clip(body.get("id", ""))
        meta = self._meta(clip)
        if (meta.get("posted") or {}) and not self.cfg.clips.keep_originals:
            src = clip.parent.parent / naming.SOURCE / clip.name
            if src.exists():
                src.unlink()
                log.info("🧹 posted %s: deleted its original", clip.name)
        return web.json_response({"ok": True})

    async def open_upload(self, request):
        body = await request.json()
        key = body.get("platform")
        url = (SIGN_IN.get(key, "about:blank") if body.get("signin") else
               (TARGETS[key].url if key in TARGETS else None))
        if not url:
            raise web.HTTPBadRequest(text="unknown platform")
        if body.get("signin") and self.cfg.post.autofill:
            # A normal Chrome window with the Clipper profile (Google blocks sign-in in automated ones).
            try:
                await self.autoposter().open_sign_in([key] if key != "all" else self._platforms())
                return web.json_response({"ok": True, "where": "clipper"})
            except Exception as e:  # noqa: BLE001
                log.warning("couldn't open Clipper's browser (%s), using your normal browser", e)
        for u in ([SIGN_IN[k] for k in self._platforms()] if key == "all" else [url]):
            webbrowser.open(u)
        return web.json_response({"ok": True, "where": "browser"})

    # ------------------------------------------------------------ auto-fill

    def autoposter(self):
        if self._autoposter is None:
            from .autopost import AutoPoster
            self._autoposter = AutoPoster(Path(self.config_path).resolve().parent / "chrome-profile")
        return self._autoposter

    async def autofill(self, request):
        """Fill in one platform's upload page for a clip, in Clipper's browser window."""
        body = await request.json()
        clip = self._clip(body.get("id", ""))
        platform = body.get("platform")
        if platform not in TARGETS:
            raise web.HTTPBadRequest(text="unknown platform")
        key = f"fill|{self._id(clip)}|{platform}"
        caps = captions_for(self._meta(clip), clip, self.cfg.post)[platform]
        # Use what's in the walkthrough's boxes right now, in case you just edited it there.
        caps.update({k: str(v) for k, v in (body.get("captions") or {}).items() if k in caps and str(v).strip()})
        self.jobs[key] = {"state": "running", "error": "", "message": "Starting"}

        def status(text: str) -> None:
            self.jobs[key]["message"] = text

        submit = bool(self.cfg.post.autosubmit and body.get("submit", True))

        async def run():
            from .autopost import FillError, NeedsSignIn, NotConfirmed
            try:
                left = await self.autoposter().fill(platform, clip, caps, status, submit=submit)
                if submit:
                    meta = self._meta(clip)
                    meta.setdefault("posted", {})[platform] = datetime.now().isoformat(timespec="seconds")
                    self._save_meta(clip, meta)
                    self.jobs[key] = {"state": "posted", "error": "", "message": left}
                    log.info("🚀 %s: %s", clip.name, left)
                else:
                    self.jobs[key] = {"state": "done", "error": "", "message": left}
                    log.info("📝 %s filled in on %s", clip.name, TARGETS[platform].name)
            except NotConfirmed as e:
                self.jobs[key] = {"state": "unconfirmed", "error": "", "message": str(e)}
                log.warning("%s on %s: %s", clip.name, TARGETS[platform].name, e)
            except NeedsSignIn:
                name = TARGETS[platform].name.split()[0]
                self.jobs[key] = {"state": "signin", "error": "",
                                  "message": f"You're not signed in to {name} in the Clipper profile yet: go to Posting, "
                                             f"click Sign in, sign in there, close that Chrome window, then press Fill in again"}
            except FillError as e:
                self.jobs[key] = {"state": "error", "error": str(e), "message": ""}
                log.warning("auto-fill on %s: %s", TARGETS[platform].name, e)
            except Exception as e:  # noqa: BLE001
                self.jobs[key] = {"state": "error", "error": f"something went wrong ({type(e).__name__}: {e})",
                                  "message": ""}
                log.warning("auto-fill on %s failed: %s", TARGETS[platform].name, e, exc_info=True)

        asyncio.create_task(run())
        return web.json_response({"ok": True, "key": key})

    async def autofill_job(self, request):
        return web.json_response(self.jobs.get(request.query.get("key", ""), {"state": "none", "error": "", "message": ""}))

    async def reveal(self, request):
        body = await request.json()
        show_file(self._clip(body.get("id", "")))
        return web.json_response({"ok": True})

    async def to_phone(self, request):
        body = await request.json()
        clip = self._clip(body.get("id", ""))
        post = Path(self.cfg.post.folder)
        post.mkdir(parents=True, exist_ok=True)
        shutil.copy2(clip, post / clip.name)
        return web.json_response({"ok": True})

    async def open_folder(self, request):
        body = await request.json()
        which = body.get("which", "clips")
        if which == "post":
            path = Path(self.cfg.post.folder)
        elif which == "streamer" and body.get("name"):
            path = (self.clips_dir / body["name"]).resolve()
            if self.clips_dir.resolve() not in path.parents:
                raise web.HTTPBadRequest()
        else:
            path = self.clips_dir
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return web.json_response({"ok": True})

    async def media(self, request):
        return web.FileResponse(self._clip(request.query.get("id", "")), headers={"Cache-Control": "no-store"})

    async def thumb(self, request):
        cid = request.query.get("id", "")
        clip = self._bin_clip(cid) if request.query.get("deleted") else self._clip(cid)
        cache = self.clips_dir / ".thumbs"
        cache.mkdir(parents=True, exist_ok=True)
        out = cache / (clip.parent.parent.name + "__" + clip.stem + ".jpg")
        if not out.exists() or out.stat().st_mtime < clip.stat().st_mtime:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.5", "-i", str(clip),
                "-frames:v", "1", "-vf", "scale=270:-2", "-q:v", "4", str(out),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **NO_WINDOW)
            await proc.wait()
        if not out.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(out)

    # ------------------------------------------------------------ settings

    def _raw(self) -> dict:
        import tomllib
        try:
            return tomllib.loads(Path(self.config_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    async def settings(self, request):
        raw = self._raw()
        defaults = Config()
        fields = []
        for section, key, label, kind, help_, options in SETTINGS:
            value = raw.get(section, {}).get(key)
            if value is None:
                value = self._default(defaults, section, key)
            fields.append({"section": section, "key": key, "label": label, "kind": kind, "help": help_,
                           "options": options, "value": value})
        p = self.cfg.post
        posting = [{"key": k, "name": TARGETS[k].name, "enabled": k in p.platforms,
                    "account": getattr(p, f"{k}_account"), "tags": getattr(p, f"{k}_tags")} for k in TARGETS]
        return web.json_response({"fields": fields, "posting": posting, "credit": p.credit, "autofill": p.autofill,
                                  "autosubmit": p.autosubmit, "pause_between_clips": p.pause_between_clips})

    @staticmethod
    def _default(cfg: Config, section: str, key: str):
        creds = {"twitch", "youtube", "kick", "anthropic"}
        if section in creds:
            return getattr(cfg.creds, f"{section}_{key}", "") if section != "anthropic" else ""
        obj = getattr(cfg, section, None)
        return getattr(obj, key, None) if obj is not None else None

    async def save_settings(self, request):
        body = await request.json()
        path = Path(self.config_path)
        text = path.read_text(encoding="utf-8")
        allowed = {(s, k): kind for s, k, _l, kind, _h, _o in SETTINGS}
        allowed.update({("post", "platforms"): "multi", ("post", "credit"): "bool", ("post", "autofill"): "bool", ("post", "autosubmit"): "bool", ("post", "pause_between_clips"): "number",
                        **{("post", f"{k}_{f}"): "text" for k in TARGETS for f in ("account", "tags")}})
        for item in body.get("values", []):
            kind = allowed.get((item.get("section"), item.get("key")))
            if not kind:
                continue
            value = item.get("value")
            if kind == "number":
                value = float(value) if "." in str(value) else int(value)
            elif kind == "bool":
                value = bool(value)
            elif kind in ("multi", "language", "lines"):
                value = [str(v).strip() for v in (value or []) if str(v).strip()]
            else:
                value = str(value or "").strip()
            text = set_value(text, item["section"], item["key"], value)
        path.write_text(text, encoding="utf-8")
        self.cfg = load_config(self.config_path)
        key = self._raw().get("anthropic", {}).get("api_key", "")
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        running = self.clip_task is not None and not self.clip_task.done()
        self.needs_restart = running
        log.info("⚙️  settings saved%s", " (restart clipping to use them)" if running else "")
        return web.json_response({"ok": True, "restart": running})

    async def test_key(self, request):
        body = await request.json()
        service = body.get("service")
        if service not in KEY_TESTS:
            raise web.HTTPBadRequest()
        fn, keys = KEY_TESTS[service]
        values = {k: str((body.get("values") or {}).get(k, "")).strip() for k in keys}
        if not all(values.values()):
            return web.json_response({"ok": False, "message": "Fill in the key first"})
        ok, msg = await asyncio.to_thread(fn, values)
        return web.json_response({"ok": ok, "message": f"The key {msg}."})

    async def check(self, request):
        from .doctor import run_checks
        buf = io.StringIO()

        def run():
            with contextlib.redirect_stdout(buf):
                run_checks(load_config(self.config_path), interactive=False)

        await asyncio.to_thread(run)
        return web.json_response({"text": buf.getvalue()})

    async def quit(self, request):
        asyncio.get_running_loop().call_later(0.3, self.quit_event.set)
        return web.json_response({"ok": True})

    # ------------------------------------------------------------ app

    async def finish_stuck(self, request):
        """The "Finish now" button: finish clips waiting in .work that nothing is working on."""
        if self.jobs.get("__recovery__", {}).get("state") != "running":
            asyncio.create_task(self._recover())
        return web.json_response({"ok": True})

    async def _recover(self) -> None:
        """Finish clips left halfway last time (shown as a rendering job while it runs)."""
        from .session import recover_unfinished
        self.jobs["__recovery__"] = {"state": "running", "error": ""}
        try:
            n = await recover_unfinished(self.cfg)
            if n:
                log.info("🩹 finished %s left unfinished", "1 clip that was" if n == 1 else f"{n} clips that were")
            from .vertical import upgrade_old_clips
            await upgrade_old_clips(self.clips_dir)
        finally:
            self.jobs["__recovery__"] = {"state": "done", "error": ""}

    def make_app(self) -> web.Application:
        app = web.Application(middlewares=[self.guard], client_max_size=4 * 1024 ** 2)
        r = app.router
        r.add_get("/", self.index)
        r.add_get("/icon.png", self.icon)
        r.add_get("/api/ping", self.ping)
        r.add_get("/api/state", self.state)
        r.add_get("/api/log", self.logs_since)
        r.add_post("/api/clipping/start", self.start_clipping)
        r.add_post("/api/clipping/stop", self.stop_clipping)
        r.add_get("/api/clips", self.clips)
        r.add_get("/api/clip", self.clip_detail)
        r.add_post("/api/clip/post-captions", self.save_post)
        r.add_post("/api/clip/render", self.rerender)
        r.add_get("/api/clip/job", self.job)
        r.add_post("/api/clip/delete", self.delete_clip)
        r.add_post("/api/clips/retry", self.retry_failed)
        r.add_post("/api/clips/finish-stuck", self.finish_stuck)
        r.add_get("/api/deleted", self.deleted)
        r.add_post("/api/deleted/restore", self.restore)
        r.add_post("/api/deleted/purge", self.purge)
        r.add_post("/api/clip/posted", self.mark_posted)
        r.add_post("/api/clip/finish", self.finish_clip)
        r.add_post("/api/clip/reveal", self.reveal)
        r.add_post("/api/clip/to-phone", self.to_phone)
        r.add_post("/api/open-upload", self.open_upload)
        r.add_post("/api/autofill", self.autofill)
        r.add_get("/api/autofill/job", self.autofill_job)
        r.add_post("/api/open-folder", self.open_folder)
        r.add_get("/api/settings", self.settings)
        r.add_post("/api/settings", self.save_settings)
        r.add_post("/api/settings/test", self.test_key)
        r.add_get("/api/check", self.check)
        r.add_post("/api/quit", self.quit)
        r.add_get("/media", self.media)
        r.add_get("/thumb", self.thumb)
        return app

    async def run(self, open_ui: bool = True, port: int = PORT, idle_exit: float = 300) -> None:
        runner = web.AppRunner(self.make_app(), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        url = f"http://127.0.0.1:{port}/"
        log.info("Clipper app ready")
        if self.cfg.phone.enabled:
            try:
                from .phone import PhoneServer
                phone = PhoneServer(self.cfg, self.config_path)
                if await phone.start():
                    self.phone = phone
            except Exception as e:  # noqa: BLE001
                log.warning("📱 Phone app couldn't start: %s", e)
        if open_ui:
            open_window(url)
        asyncio.create_task(self._recover())
        try:
            while not self.quit_event.is_set():
                try:
                    await asyncio.wait_for(self.quit_event.wait(), 10)
                except asyncio.TimeoutError:
                    pass
                idle = time.time() - self.last_seen > idle_exit
                busy = (self.clip_task and not self.clip_task.done()) or any(
                    j["state"] == "running" for j in self.jobs.values())
                if idle_exit and idle and not busy:
                    log.info("window closed and nothing running: exiting")
                    break
        finally:
            await self.stop_clipping()
            if self._autoposter is not None:
                await self._autoposter.close()
            if self.phone:
                await self.phone.stop()
            await runner.cleanup()


def open_window(url: str) -> None:
    """Open the app in its own window (no address bar) where possible, else in the browser."""
    candidates = []
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                       Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    for exe in candidates:
        if exe.exists():
            try:
                subprocess.Popen([str(exe), f"--app={url}", "--window-size=1400,900"], **NO_WINDOW)
                return
            except OSError:
                continue
    webbrowser.open(url)


async def already_running(port: int = PORT) -> bool:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"http://127.0.0.1:{port}/api/ping", timeout=aiohttp.ClientTimeout(total=1.5)) as r:
                return (await r.json()).get("app") == "clipper"
    except Exception:  # noqa: BLE001
        return False


def setup_file_log(folder: Path) -> None:
    """The app has no console window, so its log goes to clipper.log (and the app's activity panel)."""
    handler = logging.handlers.RotatingFileHandler(folder / "clipper.log", maxBytes=2_000_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for noisy in ("asyncio", "httpx", "httpcore", "anthropic", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def main(config_path: str = "config.toml", open_ui: bool = True) -> None:
    if await already_running():
        open_window(f"http://127.0.0.1:{PORT}/")
        return
    setup_file_log(Path(config_path).resolve().parent)
    await ClipperApp(config_path).run(open_ui=open_ui)
