"""Keeps helper programs (ffmpeg, streamlink, ...) from flashing black console windows on Windows
when the clipper runs as a desktop app without a console of its own."""
import sys

NO_WINDOW: dict = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW
