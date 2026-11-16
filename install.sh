#!/usr/bin/env bash
# Stream Clipper installer for Mac (and Linux).
# Double-click install.command on a Mac, or run:  bash install.sh
set -euo pipefail

REPO_URL="https://github.com/sludde05-coder/clipper"
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✘ %s\033[0m\n' "$*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Can we ask the user questions? (Not when piped from curl without a terminal.)
INTERACTIVE=0
if [ -z "${CLIPPER_NONINTERACTIVE:-}" ] && (exec </dev/tty) 2>/dev/null; then INTERACTIVE=1; fi

echo "=============================================="
echo "   Stream Clipper installer"
echo "=============================================="
echo "This installs Python, ffmpeg and everything the clipper needs."
echo "It can take 5-15 minutes. You may be asked for your computer password."

OS="$(uname -s)"

# ---------------------------------------------------------------- system tools
if [ "$OS" = "Darwin" ]; then
  step "Checking Homebrew (installs the tools below)"
  if ! have brew; then
    for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$p" ] && eval "$("$p" shellenv)"; done
  fi
  if ! have brew; then
    warn "Homebrew not found: installing it. Type your Mac password when asked (nothing shows while typing)."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
    for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$p" ] && eval "$("$p" shellenv)"; done
    have brew || die "Homebrew didn't install. See https://brew.sh and run this installer again."
    # Make brew available in future Terminal windows too.
    BREW_LINE="eval \"\$($(command -v brew) shellenv)\""
    grep -qsF "$BREW_LINE" ~/.zprofile || echo "$BREW_LINE" >> ~/.zprofile
  fi
  ok "Homebrew"
fi

install_pkgs() {  # install_pkgs <mac names> -- <apt names> -- <dnf names>
  local mac=() apt=() dnf=() part=mac
  for a in "$@"; do
    if [ "$a" = "--" ]; then [ $part = mac ] && part=apt || part=dnf; continue; fi
    case $part in mac) mac+=("$a");; apt) apt+=("$a");; dnf) dnf+=("$a");; esac
  done
  if [ "$OS" = "Darwin" ]; then brew install "${mac[@]}"
  elif have apt-get; then sudo apt-get update -qq && sudo apt-get install -y "${apt[@]}"
  elif have dnf; then sudo dnf install -y "${dnf[@]}"
  else die "Please install these yourself, then run this again: ${apt[*]}"
  fi
}

# 3.11-3.13 only: the speech package has no builds for newer Python yet.
python_ok() { "$1" -c 'import sys, venv, ensurepip; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null; }
find_python() {
  local c
  for c in python3.13 python3.12 python3.11 python3 python; do
    if have "$c" && python_ok "$(command -v "$c")"; then command -v "$c"; return 0; fi
  done
  if [ "$OS" = "Darwin" ] && have brew; then
    for c in "$(brew --prefix)"/bin/python3.1[1-9]; do
      [ -x "$c" ] && python_ok "$c" && { echo "$c"; return 0; }
    done
  fi
  return 1
}

step "Checking Python (needs version 3.11, 3.12 or 3.13)"
if ! PY="$(find_python)"; then
  warn "No suitable Python found: installing Python 3.12 (any other Python stays as it is)"
  install_pkgs python@3.12 -- python3 python3-venv python3-pip -- python3 python3-pip
  hash -r
  PY="$(find_python)" || die "Python 3.11-3.13 still not found. Install Python 3.12 from python.org and run this again."
fi
ok "Python: $("$PY" --version) ($PY)"

step "Checking ffmpeg (cuts the video)"
if ! have ffmpeg; then
  warn "Not found: installing ffmpeg"
  install_pkgs ffmpeg -- ffmpeg -- ffmpeg
  hash -r
  have ffmpeg || die "ffmpeg didn't install. Install it yourself and run this again."
fi
ok "ffmpeg"

# ---------------------------------------------------------------- the project
# Run from inside the project folder, or (curl | bash) download it first.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
if [ -f "$HERE/requirements.txt" ] && [ -d "$HERE/clipper" ]; then
  cd "$HERE"
else
  step "Downloading the project to ~/clipper"
  have git || install_pkgs git -- git -- git
  if [ -d "$HOME/clipper/.git" ]; then git -C "$HOME/clipper" pull --ff-only; else git clone "$REPO_URL" "$HOME/clipper"; fi
  cd "$HOME/clipper"
fi
ok "Project folder: $(pwd)"

step "Installing the clipper's Python packages (the slow part)"
if [ -e .venv/bin/python ] && ! python_ok .venv/bin/python; then
  warn "Rebuilding the clipper's environment with $("$PY" --version)"
  rm -r .venv
fi
if [ ! -x .venv/bin/python ]; then "$PY" -m venv .venv; fi
VPY="$(pwd)/.venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r requirements.txt
ok "Packages installed"

step "Installing speech-to-text (for word-by-word captions)"
SPEECH=0
if "$VPY" -m pip install --quiet -r requirements-speech.txt; then SPEECH=1; ok "Speech-to-text installed"
else warn "Couldn't install it. Clips still get captions, just not word-by-word ones."; fi

if [ ! -f config.toml ]; then cp config.example.toml config.toml; ok "Created config.toml"; fi
chmod +x Clipper.command install.command install.sh 2>/dev/null || true

step "Checking the clipper works"
SELFTEST="$("$VPY" -m clipper -c none simulate 2>&1 || true)"
if grep -q "fired" <<<"$SELFTEST"; then ok "Self-test passed"; else echo "$SELFTEST"; die "Self-test failed. Send the output above to get help."; fi

if [ "$SPEECH" = 1 ]; then
step "Downloading the speech-to-text model (~500 MB, one time)"
if "$VPY" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" >/dev/null 2>&1; then
  ok "Speech model ready"
else
  warn "Couldn't download it now. It will download automatically with the first clip."
fi
fi

# ---------------------------------------------------------------- keys
if [ "$INTERACTIVE" = 1 ]; then
  step "API keys"
  "$VPY" -m clipper setup </dev/tty || warn "Key setup stopped. Run it later from the menu (option 6)."
else
  warn "Skipping key setup (no keyboard input). Open the clipper and choose option 6."
fi

echo
echo "=============================================="
printf '\033[1;32m   ✔ All done!\033[0m\n'
echo "=============================================="
if [ "$OS" = "Darwin" ]; then
  echo "To start: double-click  Clipper.command  in the $(basename "$(pwd)") folder."
else
  echo "To start:  $(pwd)/Clipper.command"
fi
echo "Tip: try option 4 first to test it on a game that's live today."
