"""Which step each clip is on while its phone clip is being made, for the app to show."""
from __future__ import annotations

import time

_steps: dict[str, tuple[str, float]] = {}
_tasks: dict[str, object] = {}       # the asyncio task making each clip
_stopped: set[str] = set()           # clips the app asked to stop (Delete on a clip being made)

WAITING = "Waiting for a free spot"  # queued behind other clips; not stuck


def step(clip_name: str, text: str) -> None:
    _steps[clip_name] = (text, time.time())


def attach(clip_name: str, task) -> None:
    _tasks[clip_name] = task


def stop(clip_name: str) -> bool:
    """Stop making this clip (its work is cancelled). True if something was running."""
    task = _tasks.get(clip_name)
    _stopped.add(clip_name)
    if task is not None and not task.done():
        task.cancel()
        return True
    return False


def was_stopped(clip_name: str) -> bool:
    return clip_name in _stopped


def forget(clip_name: str) -> None:
    _stopped.discard(clip_name)


def done(clip_name: str) -> None:
    _steps.pop(clip_name, None)
    _tasks.pop(clip_name, None)


def get(clip_name: str) -> tuple[str, float] | None:
    return _steps.get(clip_name)
