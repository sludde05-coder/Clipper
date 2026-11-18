"""Rolling video buffer.

streamlink pulls the live stream and pipes it into ffmpeg, which cuts it into
short .ts segments named by wall-clock start time. Old segments are deleted,
so disk use stays at a few minutes per channel. When a clip is wanted, the
segments covering that time range are joined into one .mp4 without re-encoding.
"""
from __future__ import annotations

import asyncio
import re
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .proc import NO_WINDOW

log = logging.getLogger(__name__)
SEG_RE = re.compile(r"^seg_(\d+)_(\d+)\.ts$")


class Recorder:
    def __init__(self, name: str, url: str, workdir: Path, *, segment_seconds: int = 2,
                 keep_seconds: int = 120, quality: str = "best",
                 source_cmd: list[str] | None = None):
        self.name = name
        self.url = url
        self.dir = workdir
        self.segment_seconds = segment_seconds
        self.keep_seconds = keep_seconds
        # Run streamlink through this same Python: the launchers don't put the
        # environment's Scripts/bin folder on PATH, so a bare "streamlink" isn't found.
        self.source_cmd = source_cmd or [sys.executable, "-m", "streamlink", "--stdout", "--loglevel", "error",
                                         "--retry-open", "3", url, quality]
        self._procs: list[subprocess.Popen] = []
        self._src_log = self.dir / "streamlink.log"
        self._ff_log = self.dir / "ffmpeg.log"

    @property
    def live(self) -> bool:
        """True while video is actually arriving (a fresh segment was written recently)."""
        segs = self.segments()
        return bool(segs) and time.time() - segs[-1][1] < self.segment_seconds * 3 + 8

    def _start(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        src_err, ff_err = open(self._src_log, "wb"), open(self._ff_log, "wb")
        src = subprocess.Popen(self.source_cmd, stdout=subprocess.PIPE, stderr=src_err, **NO_WINDOW)
        ff = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-map", "0:v?", "-map", "0:a?", "-c", "copy",
             "-f", "segment", "-segment_time", str(self.segment_seconds),
             "-reset_timestamps", "1",
             # Numbered, with a per-start prefix so a restart never overwrites older pieces.
             str(self.dir / f"seg_{int(time.time() * 1000)}_%06d.ts")],
            stdin=src.stdout, stderr=ff_err, **NO_WINDOW)
        src_err.close()  # the child processes keep their own handles
        ff_err.close()
        src.stdout.close()  # ffmpeg owns the pipe now
        self._procs = [src, ff]

    def _stop(self) -> None:
        for p in self._procs:
            if p.poll() is None:
                p.terminate()
        for p in self._procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        self._procs = []

    async def run(self) -> None:
        backoff = 5
        try:
            while True:
                try:
                    self._start()
                except OSError as e:
                    log.error("%s can't start recording: %s", self.name, e)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 120)
                    continue
                started = time.time()
                announced = False
                while all(p.poll() is None for p in self._procs):
                    self.prune()
                    if not announced and self.live:
                        log.info("%s recording", self.name)
                        announced = True
                    elif not announced and time.time() - started > 60:
                        log.warning("%s: no video after 60 s. %s", self.name, self._last_error() or "still waiting")
                        announced = True
                    await asyncio.sleep(2)
                self._stop()
                if time.time() - started > 60:
                    backoff = 5
                log.warning("%s recording stopped (%s), retrying in %ss",
                            self.name, self._last_error() or "stream ended or went offline", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)
        finally:
            self._stop()

    def _last_error(self) -> str:
        # streamlink's message explains the cause; ffmpeg's ("Invalid data") is usually just the effect.
        for path in (self._src_log, self._ff_log):
            try:
                lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
            except OSError:
                continue
            if lines:
                return lines[-1][:200]
        return ""

    def segments(self) -> list[tuple[float, float, Path]]:
        """(start, end, path) for each buffered piece, oldest first, in wall-clock time.

        A piece's end is when ffmpeg last wrote to it (its modified time), and the next piece
        starts right then, which is accurate to a fraction of a second. The first piece of a
        recording run has no predecessor, so its start is estimated from the nominal length."""
        found = []
        for p in self.dir.glob("seg_*.ts"):
            m = SEG_RE.match(p.name)
            if not m:
                continue
            try:
                found.append((int(m.group(1)), int(m.group(2)), p.stat().st_mtime, p))
            except OSError:
                continue  # pruned meanwhile
        found.sort()
        out: list[tuple[float, float, Path]] = []
        prev_run, prev_num, prev_end = None, None, None
        for run, num, mtime, p in found:
            if run == prev_run and num == prev_num + 1:
                start = prev_end
            else:
                start = mtime - self.segment_seconds
            out.append((start, mtime, p))
            prev_run, prev_num, prev_end = run, num, mtime
        return out

    def prune(self) -> None:
        cutoff = time.time() - self.keep_seconds
        for start, end, p in self.segments():
            if end < cutoff:
                p.unlink(missing_ok=True)

    async def save_clip(self, start: float, end: float, out: Path) -> float | None:
        """Write exactly start..end; returns the wall-clock time of its first frame, or None.

        The buffer is in whole segments, so the joined segments are trimmed to the exact
        second. That needs a re-encode, which also gives every clip clean keyframes."""
        segs = self.segments()[:-1]  # newest one is still being written
        picked = [(s, p) for s, e, p in segs if e > start and s < end]
        if not picked:
            log.error("%s no buffered video for %s..%s", self.name, start, end)
            return None
        chosen = [p for _, p in picked]
        out.parent.mkdir(parents=True, exist_ok=True)
        # Copy first so pruning can't delete a segment mid-concat.
        tmp = out.with_suffix(".parts")
        tmp.mkdir(exist_ok=True)
        listing = tmp / "list.txt"
        lines = []
        for i, p in enumerate(chosen):
            dst = tmp / f"{i:04d}.ts"
            try:
                shutil.copyfile(p, dst)
            except FileNotFoundError:
                continue
            lines.append(f"file '{dst.name}'")
        listing.write_text("\n".join(lines), encoding="utf-8")
        first = picked[0][0]
        skip = max(0.0, start - first)                 # into the first segment
        length = end - max(start, first)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-ss", f"{skip:.3f}", "-t", f"{length:.3f}",
            "-map", "0:v?", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
            stderr=asyncio.subprocess.PIPE, **NO_WINDOW)
        _, err = await proc.communicate()
        shutil.rmtree(tmp, ignore_errors=True)
        if proc.returncode != 0:
            log.error("%s ffmpeg concat failed: %s", self.name, err.decode(errors="replace")[-500:])
            return None
        return first + skip
