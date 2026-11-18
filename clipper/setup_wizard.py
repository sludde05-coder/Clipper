"""Interactive helpers for people who'd rather not edit files or type commands.

  python -m clipper setup   – walks through each API key: opens the right web page,
                              explains what to click, checks the key works, saves it
  python -m clipper menu    – a numbered menu for everything the app does
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------- config file editing


def set_value(text: str, section: str, key: str, value: str) -> str:
    """Set key = "value" inside [section] of a TOML file, keeping comments and layout."""
    quoted = json.dumps(value)  # a valid TOML basic string for anything a key contains
    lines = text.splitlines()
    header = re.compile(rf"^\s*\[{re.escape(section)}\]\s*(#.*)?$")
    start = next((i for i, ln in enumerate(lines) if header.match(ln)), None)
    if start is None:
        lines += ["", f"[{section}]", f"{key} = {quoted}"]
        return "\n".join(lines) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    entry = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(\[[^\]]*\]|\"[^\"]*\"|'[^']*'|\S+)(.*)$")
    for i in range(start + 1, end):
        m = entry.match(lines[i])
        if m:
            lines[i] = f"{m.group(1)}{quoted}{m.group(3)}"
            return "\n".join(lines) + "\n"
    lines.insert(start + 1, f"{key} = {quoted}")
    return "\n".join(lines) + "\n"


def get_value(text: str, section: str, key: str) -> str:
    import tomllib
    try:
        return str(tomllib.loads(text).get(section, {}).get(key, "") or "")
    except tomllib.TOMLDecodeError:
        return ""


def ensure_config(path: Path) -> None:
    if not path.exists():
        example = path.with_name("config.example.toml")
        shutil.copyfile(example, path)
        print(f"Created {path.name} from {example.name}.")


# ---------------------------------------------------------------- key checks
# Each returns (ok, message). ok=None means "couldn't tell" (e.g. no internet).


# Identify as this app rather than the generic "Python-urllib", which some APIs refuse.
APP_HEADERS = {"User-Agent": "Clipper/1.0 (+https://github.com/sludde05-coder/clipper)", "Accept": "application/json"}


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        **APP_HEADERS, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _check(fn: Callable[[], None]) -> tuple[bool | None, str]:
    try:
        fn()
        return True, "works"
    except urllib.error.HTTPError as e:
        try:
            body = e.read(2000).decode(errors="replace").lower()
        except Exception:  # noqa: BLE001
            body = ""
        if e.code == 403 and ("<html" in body or "cloudflare" in body):
            # A web page instead of an API answer: the site refused the request itself.
            return None, ("couldn't be checked: the site refused the request before looking at the key "
                          "(403 from its protection layer). This doesn't mean the key is wrong")
        if e.code in (400, 401):
            return False, f"was rejected ({e.code}). Check you copied the right one (a fresh secret if you made a new one)"
        if e.code == 403:
            return False, "was refused (403). The app may not be allowed to do this yet; check its settings on the site"
        return None, f"couldn't be checked (server said {e.code})"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"couldn't be checked (no connection: {getattr(e, 'reason', e)})"


def check_twitch(v: dict) -> tuple[bool | None, str]:
    return _check(lambda: _post("https://id.twitch.tv/oauth2/token", {
        "client_id": v["client_id"], "client_secret": v["client_secret"], "grant_type": "client_credentials"}))


def check_youtube(v: dict) -> tuple[bool | None, str]:
    # Looking up one video by id costs 1 of the 10,000 daily quota units.
    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(
        {"part": "id", "id": "jNQXAC9IVRw", "key": v["api_key"]})
    return _check(lambda: urllib.request.urlopen(url, timeout=15).read())


def check_kick(v: dict) -> tuple[bool | None, str]:
    return _check(lambda: _post("https://id.kick.com/oauth/token", {
        "client_id": v["client_id"], "client_secret": v["client_secret"], "grant_type": "client_credentials"}))


def check_anthropic(v: dict) -> tuple[bool | None, str]:
    try:
        import anthropic
    except ImportError:
        return None, "couldn't be checked (anthropic package missing)"
    try:
        anthropic.Anthropic(api_key=v["api_key"]).models.list(limit=1)
        return True, "works"
    except anthropic.AuthenticationError:
        return False, "was rejected. It was probably copied wrong"
    except anthropic.PermissionDeniedError:
        return False, "has no access. Check that your account has credit"
    except anthropic.APIConnectionError:
        return None, "couldn't be checked (no connection)"
    except anthropic.APIStatusError as e:
        return None, f"couldn't be checked (server said {e.status_code})"


# ---------------------------------------------------------------- wizard


@dataclass
class Service:
    section: str
    name: str
    why: str
    url: str
    steps: list[str]
    fields: list[tuple[str, str]]   # (config key, what to call it)
    check: Callable[[dict], tuple[bool | None, str]]


SERVICES = [
    Service(
        "twitch", "Twitch", "finds the biggest Twitch streams (most important)",
        "https://dev.twitch.tv/console/apps",
        ["Log in with Twitch. Two-factor login must be on: twitch.tv → Settings → Security.",
         "Click 'Register Your Application'.",
         "Name: anything unique, e.g. yourname-clipper",
         "OAuth Redirect URLs: http://localhost  → click Add",
         "Category: Other    Client Type: Confidential  → Create",
         "Click 'Manage' next to your app. Copy the Client ID.",
         "Click 'New Secret' and copy the secret (only shown once)."],
        [("client_id", "Client ID"), ("client_secret", "Client Secret")], check_twitch),
    Service(
        "youtube", "YouTube", "finds the biggest YouTube streams",
        "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
        ["Sign in with Google and accept the terms (no card needed).",
         "If asked, create a project (any name, e.g. clipper) and select it.",
         "Click 'Enable' for YouTube Data API v3.",
         "Open the menu → APIs & Services → Credentials.",
         "Click '+ Create credentials' → 'API key'. Copy it (starts with AIza)."],
        [("api_key", "API key")], check_youtube),
    Service(
        "kick", "Kick", "finds the biggest Kick streams",
        "https://kick.com/settings/developer",
        ["Log in to Kick (two-factor login may need to be on).",
         "Create an app: any name, redirect URL http://localhost.",
         "Copy the Client ID and Client Secret."],
        [("client_id", "Client ID"), ("client_secret", "Client Secret")], check_kick),
    Service(
        "anthropic", "Anthropic (Claude)", "lets Claude write the captions; optional, costs a few cents per clip",
        "https://console.anthropic.com/settings/keys",
        ["Sign up or log in.",
         "Go to Billing and add some credit ($5 lasts well over a hundred clips).",
         "Go to API Keys → Create Key. Copy it (starts with sk-ant-, only shown once)."],
        [("api_key", "API key")], check_anthropic),
]


def ask(prompt: str, default: bool = True) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        a = input(f"{prompt} {hint} ").strip().lower()
        if not a:
            return default
        if a in ("y", "yes", "j", "ja"):
            return True
        if a in ("n", "no", "nej"):
            return False


def ask_text(prompt: str) -> str:
    # Pasted keys often come with stray spaces or quotes.
    return input(f"  Paste the {prompt} here and press Enter: ").strip().strip("\"'").strip()


def mask(v: str) -> str:
    return v[:4] + "…" + v[-3:] if len(v) > 10 else "set"


def run_wizard(path: str = "config.toml") -> None:
    cfg = Path(path)
    ensure_config(cfg)
    print("\n=== API key setup ===")
    print("The keys let the app find the biggest live streams. You need at least Twitch.")
    print("For each one, a web page opens. Follow the steps, then paste what you copied here.")
    print("(To paste: Ctrl+V, or right-click, in Windows; Cmd+V on a Mac.)\n")

    for s in SERVICES:
        text = cfg.read_text(encoding="utf-8")
        current = {k: get_value(text, s.section, k) for k, _ in s.fields}
        print(f"── {s.name}: {s.why}")
        if all(current.values()):
            print(f"   Already set ({', '.join(mask(v) for v in current.values())}).")
            if not ask("   Change it?", default=False):
                print()
                continue
        elif not ask(f"   Set up {s.name} now?", default=s.section != "kick"):
            print()
            continue

        try:
            webbrowser.open(s.url)
            print(f"   Opened {s.url}")
        except Exception:  # noqa: BLE001
            print(f"   Open this page: {s.url}")
        for i, step in enumerate(s.steps, 1):
            print(f"     {i}. {step}")

        while True:
            values = {k: ask_text(label) for k, label in s.fields}
            if not all(values.values()):
                print("   Nothing pasted.")
                if ask("   Try again?"):
                    continue
                break
            print("   Checking…", end=" ", flush=True)
            ok, msg = s.check(values)
            print(f"the key {msg}.")
            if ok is False and ask("   Try again?"):
                continue
            if ok is False and not ask("   Save it anyway?", default=False):
                break
            for k, v in values.items():
                text = set_value(text, s.section, k, v)
            cfg.write_text(text, encoding="utf-8")
            print(f"   ✅ Saved {s.name}.")
            break
        print()

    text = cfg.read_text(encoding="utf-8")
    have = [s.name for s in SERVICES if all(get_value(text, s.section, k) for k, _ in s.fields)]
    print("Keys saved for: " + (", ".join(have) if have else "nothing yet"))
    if not any(n in have for n in ("Twitch", "YouTube", "Kick")):
        print("⚠️  Without a Twitch, YouTube or Kick key the app can't find the top streams.")
        print("   You can still clip specific streamers (menu option 3), or run setup again later.")


# ---------------------------------------------------------------- menu


MENU = """
==============================================
   STREAM CLIPPER
==============================================
  1) Start clipping: the top 10 GTA 6 streams
  2) Show who's in the top 10 right now
  3) Clip specific streamers
  4) Test on a game that's live right now
  5) Open the clips folder
  6) Set up or change API keys
  7) Post clips on this PC (drop them in the POST folder)
  8) Phone app: post clips from your phone
  9) Check that everything works
 10) Quit
"""


def _run(*args: str) -> None:
    proc = subprocess.Popen([sys.executable, "-m", "clipper", *args])
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.wait()
        print("\nStopped.")


def open_folder(path: Path) -> None:
    path.mkdir(exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])


def run_menu() -> None:
    if not Path("config.toml").exists():
        print("First time? Let's set up your API keys.")
        run_wizard()
    while True:
        print(MENU)
        try:
            choice = input("Type a number and press Enter: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        try:
            if choice == "1":
                print("\nClipping. Leave this window open. Press Ctrl+C to stop.\n")
                _run("run")
            elif choice == "2":
                _run("discover")
            elif choice == "3":
                print("\nType streamers separated by spaces, like:  twitch:kaicenat kick:adinross")
                print("(For YouTube, paste the link to the live video.)")
                targets = input("Streamers: ").split()
                if targets:
                    print("\nClipping. Press Ctrl+C to stop.\n")
                    _run("watch", *targets)
            elif choice == "4":
                game = input("Which game? (press Enter for Grand Theft Auto V): ").strip() or "Grand Theft Auto V"
                print("\nClipping the top streams of that game. Press Ctrl+C to stop.\n")
                _run("run", "--game", game)
            elif choice == "5":
                open_folder(Path("clips"))
            elif choice == "6":
                run_wizard()
            elif choice == "7":
                open_folder(Path("POST"))
                _run("post")
            elif choice == "8":
                print("\nThe phone app also runs by itself whenever the clipper is clipping (options 1, 3, 4).")
                _run("phone")
            elif choice == "9":
                _run("check")
            elif choice in ("10", "q", "quit", "exit"):
                return
        except KeyboardInterrupt:
            print("\nStopped.")
