"""Where clips go and what they're called.

    clips/<Streamer>/Phone clips/<Streamer>_<YYYY-MM-DD>_<HH-MM-SS>_<n>.mp4
    clips/<Streamer>/Captions and details/<Streamer>_<YYYY-MM-DD>_<HH-MM-SS>_<n>.json

The 16:9 original is only kept while the phone version is made (in .work), unless
keep_originals is on (then in Originals/). If the phone version fails it's kept in
Not converted/, and clips in another language in Other languages/.

n counts that streamer's clips (1, 2, 3, ...), across days and restarts. The time is when
chat exploded, in this PC's time zone. Windows doesn't allow ":" in names, hence the dashes.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

COUNT_FILE = ".clip-count"
PHONE = "Phone clips"
DETAILS = "Captions and details"
WORK = ".work"
ORIGINALS = "Originals"
NOT_CONVERTED = "Not converted"
OTHER_LANGUAGES = "Other languages"
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
    """Where to save the original while it's being processed: <Streamer>/.work/<name>.mp4."""
    name = safe_name(streamer)
    folder = Path(output_dir) / name
    n = next_number(folder)
    stamp = datetime.fromtimestamp(when).strftime("%Y-%m-%d_%H-%M-%S")
    return folder / WORK / f"{name}_{stamp}_{n}.mp4", n


def streamer_dir(work_clip: Path) -> Path:
    return work_clip.parent.parent


def phone_path(work_clip: Path) -> Path:
    return streamer_dir(work_clip) / PHONE / work_clip.name


def details_path(work_clip: Path) -> Path:
    return streamer_dir(work_clip) / DETAILS / (work_clip.stem + ".json")


def move_into(path: Path, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / path.name
    path.replace(dest)
    return dest
