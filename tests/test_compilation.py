"""Top N countdowns made from finished phone clips."""
import asyncio
import json
import subprocess
from datetime import datetime

from clipper import compilation as comp
from clipper import naming
from clipper.poster import captions_for
from clipper.vertical import probe_size, probe_video_duration


def phone_clip(root, streamer, n, color, rate, seconds=20, offset=12.0, platform="twitch"):
    clip = root / streamer / naming.PHONE / f"{streamer}_2026-11-19_21-0{n}-00_{n}.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color={color}:size=1080x1920:rate=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=d={seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(clip)], check=True)
    det = root / streamer / naming.DETAILS / (clip.stem + ".json")
    det.parent.mkdir(parents=True, exist_ok=True)
    det.write_text(json.dumps({"name": streamer, "platform": platform, "url": f"https://x/{streamer}",
                               "chat_rate": rate, "normal_rate": 1.0, "explosion_offset": offset,
                               "explosion_at": datetime.now().isoformat(timespec="seconds"),
                               "captions": {"hook": f"{streamer} did a thing 😭"}}), encoding="utf-8")
    return clip


def pixel(path, t, x, y):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                         capture_output=True).stdout
    return tuple(raw[:3])


def test_countdown_ranks_by_the_biggest_moment(tmp_path):
    small = phone_clip(tmp_path, "Lacy", 1, "red", rate=5, platform="kick")
    big = phone_clip(tmp_path, "xQc", 2, "blue", rate=40)
    mid = phone_clip(tmp_path, "Kai", 3, "0x00ff00", rate=20, seconds=8, offset=4)
    # today's picks: biggest first, compilations left out
    assert comp.pick_best(tmp_path, 5) == [big, mid, small]
    out = asyncio.run(comp.build(tmp_path, [small, big, mid], "Top 3 GTA 6 moments today 😭"))
    assert out.parent == tmp_path / comp.FOLDER / naming.PHONE and probe_size(out) == (1080, 1920)
    # 2 s title + 14 s (Lacy, #3) + 8 s (Kai, #2, a short clip) + 14 s (xQc, #1)
    assert abs(probe_video_duration(out) - 38) < 1
    assert pixel(out, 9, 540, 1200)[0] > 200                 # #3 is the smallest moment (red) ...
    assert pixel(out, 20, 540, 1200)[1] > 200                # ... #2 green ...
    assert pixel(out, 30, 540, 1200)[2] > 200                # ... and #1 the biggest (blue) comes last
    meta = json.loads((tmp_path / comp.FOLDER / naming.DETAILS / (out.stem + ".json")).read_text(encoding="utf-8"))
    assert [(p["rank"], p["name"]) for p in meta["compilation"]] == [(3, "Lacy"), (2, "Kai"), (1, "xQc")]
    caps = captions_for(meta, out)
    assert "#3 Lacy (Kick) · #2 Kai (Twitch) · #1 xQc (Twitch)" in caps["tiktok"]["caption"]
    assert caps["youtube"]["title"].startswith("Top 3 GTA 6 moments today") and "#top3" in caps["tiktok"]["caption"]
    # a compilation isn't picked for the next one
    assert out not in comp.pick_best(tmp_path, 5)


def test_window_is_around_the_explosion():
    assert comp.window({"explosion_offset": 30}, 45) == (20, 34)
    assert comp.window({"explosion_offset": 3}, 45) == (0, 14)
    assert comp.window({"explosion_offset": 40}, 45) == (30, 44)
    assert comp.window({"explosion_offset": 5}, 8) == (0, 8)
