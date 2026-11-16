"""Semi-automatic posting: drop a clip into the POST folder and the clipper walks you through
posting it to TikTok, YouTube Shorts and Instagram Reels.

For each platform it copies a caption written for that platform, opens the upload page
in your browser and shows the clip file, so you only drag the file in, paste and press Post.
Nothing is uploaded behind your back, so no app approvals are needed and there's no ban risk.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import PostConfig

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
PLATFORM_NAMES = {"twitch": "Twitch", "youtube": "YouTube", "kick": "Kick"}


@dataclass
class Target:
    key: str
    name: str
    url: str
    steps: list[str]


TARGETS = {
    "tiktok": Target("tiktok", "TikTok", "https://www.tiktok.com/tiktokstudio/upload", [
        "Drag the clip from the folder window onto the TikTok page (or click 'Select video').",
        "Click the description box, delete what's there, and paste (Ctrl+V / Cmd+V).",
        "Click Post.",
    ]),
    "youtube": Target("youtube", "YouTube Shorts", "https://www.youtube.com/upload", [
        "Drag the clip onto the YouTube upload window. Vertical clips under 3 minutes become Shorts.",
        "Paste the title into the Title box.",
    ]),
    "instagram": Target("instagram", "Instagram Reels", "https://www.instagram.com/", [
        "Click '+ Create' (left menu) → Post, and drag the clip in. Videos are posted as Reels.",
        "Pick the 9:16 crop if asked, click Next twice, and paste the caption.",
        "Click Share.",
    ]),
}


# ---------------------------------------------------------------- captions


def find_metadata(clip: Path, clips_dir: Path) -> dict:
    """The clip's .json from the clipper (next to it, or in the clips folder)."""
    stem = re.sub(r"_vertical$", "", clip.stem)
    for folder in (clip.parent, clips_dir, clips_dir / "other-languages"):
        p = folder / f"{stem}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    return {}


def _hashtags(text: str) -> list[str]:
    return re.findall(r"#\w+", text)


def _strip_tags(text: str) -> str:
    return re.sub(r"\s*#\w+", "", text).strip()


def build_captions(meta: dict, clip: Path, credit: bool = True) -> dict[str, dict[str, str]]:
    cap = meta.get("captions") or {}
    hook = (cap.get("hook") or "").strip()
    post = (cap.get("post_caption") or "").strip()
    name = meta.get("name") or meta.get("channel") or ""
    where = PLATFORM_NAMES.get(meta.get("platform", ""), "")
    url = meta.get("url", "")

    line = _strip_tags(post) or hook or re.sub(r"[_-]+", " ", re.sub(r"_vertical$", "", clip.stem))
    tags = _hashtags(post) or ["#gta6", "#clips"]
    if where and f"#{where.lower()}" not in [t.lower() for t in tags]:
        tags.append(f"#{where.lower()}")
    credit_line = f"🎥 {name} on {where}" if (credit and name and where) else ""

    def with_tags(extra: list[str]) -> str:
        seen, out = set(), []
        for t in tags + extra:
            if t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return " ".join(out)

    title = (hook or line)
    yt_title = (title[: 100 - len(" #shorts")].rstrip() + " #shorts") if title else "#shorts"
    return {
        "tiktok": {"caption": "\n".join(x for x in (line, credit_line, with_tags(["#fyp"])) if x)},
        "youtube": {
            "title": yt_title,
            "description": "\n".join(x for x in (
                line,
                f"{credit_line}: {url}" if credit_line and url else credit_line,
                with_tags(["#shorts"])) if x),
        },
        "instagram": {"caption": "\n\n".join(x for x in (line, credit_line, with_tags(["#reels"])) if x)},
    }


def captions_text(caps: dict[str, dict[str, str]]) -> str:
    parts = []
    for key, fields in caps.items():
        parts.append(f"===== {TARGETS[key].name} =====")
        for field, value in fields.items():
            parts.append(f"--- {field} ---\n{value}")
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------- desktop helpers


def copy_to_clipboard(text: str) -> bool:
    try:
        if sys.platform == "win32":
            # Passing the text through an environment variable keeps emoji intact.
            env = {**os.environ, "CLIPPER_CLIP": text}
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $env:CLIPPER_CLIP"],
                               env=env, capture_output=True, timeout=15)
            return r.returncode == 0
        if sys.platform == "darwin":
            env = {**os.environ, "LANG": "en_US.UTF-8"}
            return subprocess.run(["pbcopy"], input=text.encode(), env=env, timeout=15).returncode == 0
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                if subprocess.run(cmd, input=text.encode(), timeout=15).returncode == 0:
                    return True
            except FileNotFoundError:
                continue
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def show_file(path: Path) -> None:
    """Open the file's folder with the file selected, ready to drag into the browser."""
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", f"/select,{path}"])
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)])
        else:
            subprocess.run(["xdg-open", str(path.parent)])
    except OSError:
        pass


def open_page(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- the POST folder


def ready_clips(folder: Path, sizes: dict[Path, int]) -> list[Path]:
    """Videos that have finished copying in (same size on two checks in a row)."""
    ready = []
    for p in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > 0 and sizes.get(p) == size:
            ready.append(p)
        sizes[p] = size
    return ready


class Poster:
    def __init__(self, cfg: PostConfig, clips_dir: Path, *,
                 ask: Callable[[str], str] = input, clipboard=copy_to_clipboard,
                 browser=open_page, reveal=show_file, say: Callable[[str], None] = print):
        self.cfg = cfg
        self.folder = Path(cfg.folder)
        self.done_dir = self.folder / "posted"
        self.clips_dir = clips_dir
        self.ask, self.clipboard, self.browser, self.reveal, self.say = ask, clipboard, browser, reveal, say
        self.targets = [TARGETS[k] for k in cfg.platforms if k in TARGETS]

    def _copy(self, label: str, text: str) -> None:
        if self.clipboard(text):
            self.say(f"   📋 {label} copied. Paste it with Ctrl+V (Cmd+V on a Mac).")
        else:
            self.say(f"   Couldn't copy automatically. Select and copy this {label}:\n\n{text}\n")

    def _wait(self, prompt: str) -> str:
        return self.ask(f"   {prompt} ").strip().lower()

    def post(self, clip: Path) -> dict[str, str]:
        meta = find_metadata(clip, self.clips_dir)
        caps = build_captions(meta, clip, self.cfg.credit)
        caption_file = clip.with_suffix(".txt")
        caption_file.write_text(captions_text({t.key: caps[t.key] for t in self.targets}), encoding="utf-8")

        who = meta.get("name") or "unknown streamer"
        self.say(f"\n🎬 New clip to post: {clip.name}  ({who})")
        if not meta:
            self.say("   (No clipper details found for this file, so the captions are generic. Edit them as you like.)")
        self.reveal(clip)
        results: dict[str, str] = {}
        for t in self.targets:
            self.say(f"\n── {t.name} ──")
            if self._wait(f"Post to {t.name}? Press Enter to start, or type s to skip:") == "s":
                results[t.key] = "skipped"
                continue
            self.browser(t.url)
            self.say(f"   Opened {t.name} in your browser. The clip is shown in the folder window.")
            for i, step in enumerate(t.steps, 1):
                self.say(f"     {i}. {step}")
            if t.key == "youtube":
                self._copy("title", caps["youtube"]["title"])
                self._wait("Press Enter once the title is pasted, to copy the description:")
                self._copy("description", caps["youtube"]["description"])
                self.say("     3. Paste it into the Description box. Then Next → Next → Next, choose Public, and Publish.")
            else:
                self._copy("caption", caps[t.key]["caption"])
            answer = self._wait("Press Enter when it's posted (or type s if you skipped it):")
            results[t.key] = "skipped" if answer == "s" else "posted"

        self.done_dir.mkdir(parents=True, exist_ok=True)
        for f in (clip, caption_file):
            if f.exists():
                f.replace(self.done_dir / f.name)
        with open(self.done_dir / "log.jsonl", "a", encoding="utf-8") as log:
            log.write(json.dumps({"clip": clip.name, "at": datetime.now().isoformat(timespec="seconds"),
                                  **results}) + "\n")
        posted = [TARGETS[k].name for k, v in results.items() if v == "posted"]
        self.say(f"\n✅ Done with {clip.name}: posted to {', '.join(posted) or 'nothing'}. "
                 f"Moved to {self.done_dir.name}/ (captions saved next to it as a .txt).")
        return results

    def watch(self, interval: float = 2.0, once: bool = False) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.say(f"Watching the {self.folder.resolve()} folder.")
        self.say("Copy or drag a clip (the _vertical.mp4 one) into it and it'll be picked up.")
        self.say("Press Ctrl+C to stop.\n")
        sizes: dict[Path, int] = {}
        while True:
            for clip in ready_clips(self.folder, sizes):
                self.post(clip)
                sizes.pop(clip, None)
                self.say(f"\nWaiting for the next clip in {self.folder.name}/ … (Ctrl+C to stop)")
            if once:
                return
            time.sleep(interval)
