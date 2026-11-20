"""Keeps helper programs (ffmpeg, streamlink, ...) from flashing black console windows on Windows
when the clipper runs as a desktop app without a console of its own."""
import sys

NO_WINDOW: dict = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW
# For heavy work that isn't urgent (making phone clips, previews, Top 10s): below-normal priority, so
# the recording of live streams always gets the CPU first.
BACKGROUND: dict = {"creationflags": 0x08000000 | 0x00004000} if sys.platform == "win32" else {}
