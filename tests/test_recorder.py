import asyncio
import logging
import sys
from pathlib import Path

from clipper.recorder import Recorder


def test_streamlink_runs_through_this_python(tmp_path):
    # The double-click launchers don't put the environment's Scripts folder on PATH,
    # so a bare "streamlink" command isn't found there (this happened on Windows).
    r = Recorder("t", "https://www.twitch.tv/x", tmp_path)
    assert r.source_cmd[:3] == [sys.executable, "-m", "streamlink"]


def test_missing_program_is_reported_not_fatal(tmp_path, caplog):
    r = Recorder("t", "u", tmp_path, source_cmd=["no-such-program-xyz"])

    async def go():
        try:
            await asyncio.wait_for(r.run(), 1)
        except asyncio.TimeoutError:
            pass

    with caplog.at_level(logging.ERROR):
        asyncio.run(go())
    assert "can't start recording" in caplog.text
    assert not r.live


def test_source_error_message_is_surfaced(tmp_path, caplog):
    fail = [sys.executable, "-c", "import sys; sys.stderr.write('error: No playable streams found\\n'); sys.exit(1)"]
    r = Recorder("t", "u", tmp_path, source_cmd=fail)

    async def go():
        try:
            await asyncio.wait_for(r.run(), 4)
        except asyncio.TimeoutError:
            pass

    with caplog.at_level(logging.WARNING):
        asyncio.run(go())
    assert "No playable streams found" in caplog.text
