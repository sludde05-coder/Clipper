"""Where clips go and what they're called.

    clips/<Streamer>/<Streamer>_<YYYY-MM-DD>_<HH-MM-SS>_<n>.mp4

n counts that streamer's clips (1, 2, 3, ...), across days and restarts. The time is when
chat exploded, in this PC's time zone. Windows doesn't allow ":" in names, hence the dashes.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

COUNT_FILE = ".clip-count"
_NUM = re.compile(r"_(\d+)(?:_vertical)?\.(?:mp4|json|txt)$")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_name(name: str) -> str:
    """A streamer name that works as a Windows/Mac file and folder name."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "_", name).strip(" ._")[:40] or "streamer"
    return f"{s}_" if s.lower() in _RESERVED else s


def next_number(folder: Path) -> int:
    """The next clip number for the streamer in this folder (doesn't reserve it)."""
    n = 0
    try:
        n = int((folder / COUNT_FILE).read_text().strip())
    except (OSError, ValueError):
        pass
    # Also look at the files, in case the count file was deleted.
    if folder.exists():
        for p in folder.rglob("*"):
            m = _NUM.search(p.name)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1


def commit_number(folder: Path, n: int) -> None:
    try:
        (folder / COUNT_FILE).write_text(str(n))
    except OSError:
        pass


def clip_path(output_dir: str | Path, streamer: str, when: float) -> tuple[Path, int]:
    name = safe_name(streamer)
    folder = Path(output_dir) / name
    n = next_number(folder)
    stamp = datetime.fromtimestamp(when).strftime("%Y-%m-%d_%H-%M-%S")
    return folder / f"{name}_{stamp}_{n}.mp4", n
