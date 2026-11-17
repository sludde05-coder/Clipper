import json
import re
from datetime import datetime

from clipper.naming import clip_path, commit_number, details_path, next_number, phone_path, safe_name
from clipper.poster import find_metadata


def test_name_format(tmp_path):
    when = datetime(2026, 11, 19, 21, 34, 12).timestamp()
    p, n = clip_path(tmp_path, "KaiCenat", when)
    assert p.name == "KaiCenat_2026-11-19_21-34-12_1.mp4" and n == 1
    assert phone_path(p) == tmp_path / "KaiCenat" / "Phone clips" / "KaiCenat_2026-11-19_21-34-12_1.mp4"
    assert details_path(p) == tmp_path / "KaiCenat" / "Captions and details" / "KaiCenat_2026-11-19_21-34-12_1.json"


def test_numbers_count_up_per_streamer(tmp_path):
    t = datetime(2026, 11, 19, 21, 0, 0).timestamp()
    for i in range(1, 4):
        p, n = clip_path(tmp_path, "KaiCenat", t + i)
        assert n == i
        phone_path(p).parent.mkdir(parents=True, exist_ok=True)
        phone_path(p).write_bytes(b"x")
        commit_number(tmp_path / "KaiCenat", n)
    assert clip_path(tmp_path, "xQc", t)[1] == 1          # other streamers start at 1


def test_number_survives_deleted_count_file_and_clips(tmp_path):
    folder = tmp_path / "KaiCenat"
    folder.mkdir()
    (folder / "KaiCenat_2026-11-19_21-00-00_7_vertical.mp4").write_bytes(b"x")
    assert next_number(folder) == 8                       # from the files
    commit_number(folder, 12)
    for f in folder.iterdir():
        if f.suffix == ".mp4":
            f.unlink()
    assert next_number(folder) == 13                      # deleting clips doesn't reuse numbers


def test_unsafe_names():
    assert safe_name('Mr: "Beast"?') == "Mr_Beast"
    assert safe_name("con") == "con_"
    assert safe_name("한국어스트리머") == "한국어스트리머"
    assert safe_name("...") == "streamer"


def test_metadata_found_in_streamer_folder(tmp_path):
    clips = tmp_path / "clips"
    (clips / "KaiCenat").mkdir(parents=True)
    (clips / "KaiCenat" / "KaiCenat_2026-11-19_21-34-12_3.json").write_text(json.dumps({"name": "KaiCenat"}))
    post = tmp_path / "POST"
    post.mkdir()
    meta = find_metadata(post / "KaiCenat_2026-11-19_21-34-12_3_vertical.mp4", clips)
    assert meta["name"] == "KaiCenat"
