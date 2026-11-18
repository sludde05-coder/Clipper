"""Which step each clip is on while its phone clip is being made, for the app to show."""
from __future__ import annotations

import time

_steps: dict[str, tuple[str, float]] = {}


def step(clip_name: str, text: str) -> None:
    _steps[clip_name] = (text, time.time())


def done(clip_name: str) -> None:
    _steps.pop(clip_name, None)


def get(clip_name: str) -> tuple[str, float] | None:
    return _steps.get(clip_name)
