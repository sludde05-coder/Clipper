"""Posts planned for later (e.g. Top 10 Part 1 at 15:00 and Part 2 an hour later).

Kept in clips/.schedule.json. The app posts them when they're due, while it's running, with
"Also click Post for me" (otherwise there's nobody to click Post).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

FILE = ".schedule.json"
PENDING, RUNNING = "pending", "running"


def _path(clips_dir: Path) -> Path:
    return Path(clips_dir) / FILE


def load(clips_dir: Path) -> list[dict]:
    try:
        items = json.loads(_path(clips_dir).read_text(encoding="utf-8"))
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def save(clips_dir: Path, items: list[dict]) -> None:
    p = _path(clips_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Keep finished ones for a couple of days so you can see what happened, then drop them.
    cutoff = (datetime.now() - timedelta(days=2)).isoformat()
    items = [i for i in items if i["state"] in (PENDING, RUNNING) or i["at"] >= cutoff]
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(items, key=lambda i: i["at"]), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def add(clips_dir: Path, clip_id: str, at: datetime, label: str) -> dict:
    item = {"key": uuid.uuid4().hex[:10], "id": clip_id, "at": at.isoformat(timespec="minutes"), "label": label,
            "state": PENDING, "message": "", "results": {}}
    items = load(clips_dir)
    items.append(item)
    save(clips_dir, items)
    return item


def update(clips_dir: Path, key: str, **changes) -> None:
    items = load(clips_dir)
    for i in items:
        if i["key"] == key:
            i.update(changes)
    save(clips_dir, items)


def cancel(clips_dir: Path, key: str) -> bool:
    items = load(clips_dir)
    keep = [i for i in items if not (i["key"] == key and i["state"] == PENDING)]
    save(clips_dir, keep)
    return len(keep) < len(items)


def due(clips_dir: Path, now: datetime | None = None) -> list[dict]:
    now_s = (now or datetime.now()).isoformat(timespec="minutes")
    return [i for i in load(clips_dir) if i["state"] == PENDING and i["at"] <= now_s]


def pending(clips_dir: Path) -> list[dict]:
    return [i for i in load(clips_dir) if i["state"] in (PENDING, RUNNING)]


def parse_times(times: list[str]) -> list[tuple[int, int]]:
    out = []
    for t in times:
        try:
            h, m = (int(x) for x in str(t).strip().replace(".", ":").split(":")[:2])
            if 0 <= h < 24 and 0 <= m < 60:
                out.append((h, m))
        except ValueError:
            continue
    return sorted(set(out))


def next_slot(clips_dir: Path, times: list[str], now: datetime | None = None) -> datetime:
    """The next of your daily posting times that doesn't have a post planned yet (or in 5 minutes if
    there are no times set)."""
    now = now or datetime.now()
    slots = parse_times(times)
    if not slots:
        return (now + timedelta(minutes=5)).replace(second=0, microsecond=0)
    taken = {i["at"] for i in pending(clips_dir)}
    for day in range(0, 30):
        d = (now + timedelta(days=day)).date()
        for h, m in slots:
            at = datetime(d.year, d.month, d.day, h, m)
            if at > now + timedelta(minutes=2) and at.isoformat(timespec="minutes") not in taken:
                return at
    return now + timedelta(minutes=5)
