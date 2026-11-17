"""`python -m clipper check`: tests every part and says in plain words what to fix."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from .config import Config
from .setup_wizard import ask, check_anthropic, check_kick, check_twitch, check_youtube

OK, BAD, WARN = "  ✔", "  ✘", "  !"
PIP = (r".venv\Scripts\python.exe -m pip install -r requirements-speech.txt" if sys.platform == "win32"
       else ".venv/bin/python -m pip install -r requirements-speech.txt")


def _say(mark: str, text: str, fix: str = "") -> None:
    print(f"{mark} {text}")
    if fix:
        print(f"      → {fix}")


def run_checks(cfg: Config, interactive: bool = True) -> int:
    problems = 0
    print("\n=== Checking everything ===\n")

    # Python + tools
    v = sys.version_info
    if (3, 11) <= v[:2] <= (3, 13):
        _say(OK, f"Python {v.major}.{v.minor}")
    else:
        problems += 1
        _say(BAD, f"Python {v.major}.{v.minor} (needs 3.11-3.13)", "run the installer again; it sets up Python 3.12")
    if shutil.which("ffmpeg"):
        _say(OK, "ffmpeg (cuts the video)")
    else:
        problems += 1
        _say(BAD, "ffmpeg not found", "run the installer again")
    try:
        import streamlink
        _say(OK, f"streamlink {streamlink.__version__} (downloads the video)")
    except ImportError:
        problems += 1
        _say(BAD, "streamlink not installed", "run the installer again")

    try:
        import qrcode  # noqa: F401
        _say(OK, "Phone app parts installed")
    except ImportError:
        problems += 1
        _say(BAD, "Phone app parts missing (the QR code can't be shown)", "run the installer again")

    # Speech-to-text
    print()
    vc = cfg.vertical
    if not vc.speech_captions:
        _say(WARN, "Speech-to-text is turned off (speech_captions = false in config.toml)",
             "set speech_captions = true so the AI knows what the streamer says")
    else:
        try:
            from faster_whisper import WhisperModel
            _say(OK, "Speech-to-text (faster-whisper) installed")
            try:
                WhisperModel(vc.whisper_model, device="cpu", compute_type="int8", local_files_only=True)
                _say(OK, f"Speech model '{vc.whisper_model}' downloaded")
            except Exception:  # noqa: BLE001
                _say(WARN, f"Speech model '{vc.whisper_model}' not downloaded yet (it downloads with the first clip)")
                if interactive and ask("      Download it now (about 500 MB)?"):
                    try:
                        WhisperModel(vc.whisper_model, device="cpu", compute_type="int8")
                        _say(OK, "Speech model downloaded")
                    except Exception as e:  # noqa: BLE001
                        problems += 1
                        _say(BAD, f"Download failed: {e}", "check your internet connection and disk space")
        except ImportError:
            problems += 1
            import sysconfig
            if sysconfig.get_platform() == "win-arm64":
                _say(BAD, "Speech-to-text can't be installed with ARM Python (it has no ARM version)",
                     "get the latest clipper and run install.bat again: it switches to x64 Python, which works")
            else:
                _say(BAD, "Speech-to-text (faster-whisper) is NOT installed: the AI can't know what streamers say",
                     f"run the installer again, or in the clipper folder run:  {PIP}")

    # AI captions
    print()
    if not vc.ai_captions:
        _say(WARN, "AI captions are turned off (ai_captions = false): using simple built-in captions")
    else:
        import os
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            problems += 1
            _say(BAD, "No Anthropic API key: using simple built-in captions instead of AI ones",
                 "menu option 6, or put the key under [anthropic] in config.toml")
        else:
            ok, msg = check_anthropic({"api_key": key})
            if ok:
                _say(OK, f"AI captions: key works, model {vc.ai_model}")
            elif ok is None:
                _say(WARN, f"AI captions: key {msg}")
            else:
                problems += 1
                _say(BAD, f"AI captions: the key {msg}", "make a new key at console.anthropic.com → API Keys")

    # Stream-finding keys
    print()
    c = cfg.creds
    found_any = False
    for name, have, check in (
        ("Twitch", c.twitch_client_id and c.twitch_client_secret,
         lambda: check_twitch({"client_id": c.twitch_client_id, "client_secret": c.twitch_client_secret})),
        ("YouTube", c.youtube_api_key, lambda: check_youtube({"api_key": c.youtube_api_key})),
        ("Kick", c.kick_client_id and c.kick_client_secret,
         lambda: check_kick({"client_id": c.kick_client_id, "client_secret": c.kick_client_secret})),
    ):
        if not have:
            _say(WARN, f"{name}: no key (its streams won't be found)")
            continue
        ok, msg = check()
        if ok is False:
            problems += 1
            _say(BAD, f"{name}: the key {msg}", "menu option 6 to enter it again")
        else:
            found_any = True
            _say(OK if ok else WARN, f"{name}: key {msg}")
    if not found_any:
        problems += 1
        _say(BAD, "No working Twitch, YouTube or Kick key: the top streams can't be found", "menu option 6")

    # What recent clips actually got
    print()
    metas = sorted((p for p in Path(cfg.clips.output_dir).rglob("*.json") if p.parent.name not in ("other-languages", "Other languages") and not p.name.startswith(".")), key=lambda p: p.stat().st_mtime)[-5:]
    if not metas:
        _say(WARN, "No clips yet, so nothing to check there")
    else:
        ai = speech = 0
        for p in metas:
            try:
                cap = json.loads(p.read_text(encoding="utf-8")).get("captions") or {}
            except (OSError, ValueError):
                continue
            ai += cap.get("source") == "claude"
            speech += bool(cap.get("transcript"))
        n = len(metas)
        _say(OK if ai == n else WARN, f"Last {n} clips: {ai} got AI captions")
        _say(OK if speech else WARN, f"Last {n} clips: {speech} had speech turned into text",
             "" if speech else "if streamers were talking, speech-to-text isn't working: see above")

    print()
    if problems:
        print(f"Found {problems} problem{'s' if problems > 1 else ''}. Fix the ✘ lines above and run this check again.")
    else:
        print("Everything looks good. ✔")
    return problems

