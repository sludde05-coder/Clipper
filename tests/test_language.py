import pytest

from clipper.language import looks_non_english, matches_language
from clipper.transcribe import Transcript, Word
from clipper.vertical import wrong_language


@pytest.mark.parametrize("title", [
    "GTA 6 DAY 1 LETS GOOO",
    "FIRST TIME PLAYING GTA 6 !socials",
    "GTA VI with the boys | 100% completion",
    "🔴 GTA 6 IS HERE",
    "[EN] GTA 6 en route to Vice City",
    "Rockstar did it again - GTA 6 review",
    "The new GTA 6 map is crazy",
])
def test_english_titles_kept(title):
    assert not looks_non_english(title)


@pytest.mark.parametrize("title", [
    "GTA 6 EN VIVO jugando con los pibes",
    "JOGANDO GTA 6 AO VIVO hoje",
    "GTA 6 [ES] primer día",
    "GTA 6 PT-BR | #brasil",
    "GTA 6 стрим первый день",
    "GTA 6 初見プレイ 生配信",
    "GTA 6 heute mit und ohne Cheats - Deutsch",
    "GTA 6 en direct avec les potes",
])
def test_foreign_titles_dropped(title):
    assert looks_non_english(title)


def test_platform_language_labels():
    assert matches_language("en", ["en"]) is True
    assert matches_language("en-GB", ["en"]) is True
    assert matches_language("English", ["en"]) is True
    assert matches_language("es", ["en"]) is False
    assert matches_language("Spanish", ["en"]) is False
    assert matches_language(None, ["en"]) is None
    assert matches_language("other", ["en"]) is None
    assert matches_language("es", []) is True


def _tr(lang, prob, n=20):
    return Transcript([Word(i, i + 0.5, "w") for i in range(n)], lang, prob)


def test_clip_language_check():
    assert wrong_language(_tr("es", 0.95), ["en"])
    assert not wrong_language(_tr("en", 0.99), ["en"])
    assert not wrong_language(_tr("es", 0.5), ["en"])       # unsure: keep
    assert not wrong_language(_tr("es", 0.95, n=3), ["en"])  # barely any speech: keep
    assert not wrong_language(_tr("es", 0.95), [])           # filter off
    assert not wrong_language(Transcript([]), ["en"])       # no transcription
