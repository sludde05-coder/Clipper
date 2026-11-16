import json

from clipper.config import PostConfig
from clipper.poster import Poster, build_captions, find_metadata, ready_clips

META = {"platform": "twitch", "channel": "kaicenat", "name": "KaiCenat", "url": "https://www.twitch.tv/kaicenat",
        "captions": {"hook": "Kai jumped the bridge in a cop car",
                     "post_caption": "Kai really pulled this off on day one 😭 #gta6 #kaicenat #gaming"}}


def test_captions_per_platform():
    c = build_captions(META, None)
    tt = c["tiktok"]["caption"]
    assert tt.startswith("Kai really pulled this off on day one 😭")
    assert "🎥 KaiCenat on Twitch" in tt
    assert "#gta6" in tt and "#fyp" in tt and "#twitch" in tt
    assert c["youtube"]["title"] == "Kai jumped the bridge in a cop car #shorts"
    assert "https://www.twitch.tv/kaicenat" in c["youtube"]["description"]
    assert "#shorts" in c["youtube"]["description"]
    assert "#reels" in c["instagram"]["caption"]
    assert c["tiktok"]["caption"].count("#gta6") == 1


def test_youtube_title_fits_100_chars():
    meta = {**META, "captions": {"hook": "x" * 150, "post_caption": ""}}
    assert len(build_captions(meta, None)["youtube"]["title"]) <= 100


def test_captions_without_metadata(tmp_path):
    clip = tmp_path / "funny_moment_vertical.mp4"
    c = build_captions({}, clip, credit=True)
    assert c["tiktok"]["caption"].startswith("funny moment")
    assert "🎥" not in c["tiktok"]["caption"]


def test_find_metadata_for_vertical_copy(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "twitch_kaicenat_20261119-131434.json").write_text(json.dumps(META))
    post = tmp_path / "POST"
    post.mkdir()
    clip = post / "twitch_kaicenat_20261119-131434_vertical.mp4"
    assert find_metadata(clip, clips)["name"] == "KaiCenat"
    assert find_metadata(post / "other.mp4", clips) == {}


def test_only_finished_copies_are_picked_up(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"1234")
    (tmp_path / "notes.txt").write_text("x")
    sizes = {}
    assert ready_clips(tmp_path, sizes) == []      # first sight: might still be copying
    f.write_bytes(b"12345678")                     # still growing
    assert ready_clips(tmp_path, sizes) == []
    assert ready_clips(tmp_path, sizes) == [f]     # same size twice: done


def test_full_walkthrough(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "twitch_kaicenat_1.json").write_text(json.dumps(META), encoding="utf-8")
    post = tmp_path / "POST"
    post.mkdir()
    clip = post / "twitch_kaicenat_1_vertical.mp4"
    clip.write_bytes(b"video")

    answers = iter(["",        # TikTok: start
                    "",        # TikTok: posted
                    "",        # YouTube: start
                    "",        # YouTube: title pasted
                    "",        # YouTube: posted
                    "s"])      # Instagram: skip
    opened, copied, shown, out = [], [], [], []
    p = Poster(PostConfig(folder=str(post)), clips, ask=lambda q: next(answers),
               clipboard=lambda t: copied.append(t) or True, browser=opened.append,
               reveal=shown.append, say=out.append)
    sizes = {}
    ready_clips(post, sizes)
    assert ready_clips(post, sizes) == [clip]
    results = p.post(clip)

    assert results == {"tiktok": "posted", "youtube": "posted", "instagram": "skipped"}
    assert opened == ["https://www.tiktok.com/tiktokstudio/upload", "https://www.youtube.com/upload"]
    assert copied[0].startswith("Kai really pulled") and "#fyp" in copied[0]
    assert copied[1] == "Kai jumped the bridge in a cop car #shorts"
    assert "#shorts" in copied[2]
    assert shown == [clip]
    done = post / "posted"
    assert (done / clip.name).exists() and not clip.exists()
    assert "===== TikTok =====" in (done / "twitch_kaicenat_1_vertical.txt").read_text(encoding="utf-8")
    log = json.loads((done / "log.jsonl").read_text().splitlines()[0])
    assert log["tiktok"] == "posted" and log["instagram"] == "skipped"
    # Already-posted clips aren't picked up again.
    assert ready_clips(post, {}) == []


def test_clipboard_failure_prints_caption(tmp_path):
    post = tmp_path / "POST"
    post.mkdir()
    clip = post / "x.mp4"
    clip.write_bytes(b"v")
    out = []
    answers = iter(["", ""])
    p = Poster(PostConfig(folder=str(post), platforms=["tiktok"]), tmp_path, ask=lambda q: next(answers),
               clipboard=lambda t: False, browser=lambda u: None, reveal=lambda f: None, say=out.append)
    p.post(clip)
    assert any("Couldn't copy automatically" in line for line in out)
