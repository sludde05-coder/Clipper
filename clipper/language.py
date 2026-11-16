"""Guessing a stream's language from its title, for when the platform doesn't say.

Only answers "is this clearly NOT English?". Titles are short, so it errs on the
side of keeping a stream ("GTA 6 DAY 1!!!" has no language at all).
"""
from __future__ import annotations

import re
import unicodedata

# Words that are common in titles in other languages but not in English ones.
FOREIGN_WORDS = {
    # Spanish
    "en vivo", "directo", "jugando", "nuevo", "juego", "hoy", "con", "los", "las", "por", "para", "primer",
    "español", "espanol", "mexico", "méxico", "argentina", "chile", "colombia",
    # Portuguese
    "ao vivo", "jogando", "jogo", "hoje", "novo", "com", "pra", "português", "portugues", "brasil",
    # French
    "en direct", "avec", "jeu", "nouveau", "aujourd'hui", "les", "français", "francais",
    # German
    "und", "mit", "neues", "heute", "spiel", "deutsch", "zum", "erste", "erstes",
    # Italian / Dutch / Turkish / Polish
    "oggi", "gioco", "italiano", "vandaag", "nederlands", "türkçe", "turkce", "bugün", "polska", "dzisiaj",
}
ENGLISH_WORDS = {"the", "and", "with", "my", "is", "in", "first", "new", "playing", "we", "this",
                 "to", "of", "on", "it", "you", "i", "are", "out", "day", "today", "stream", "w/"}
FOREIGN_TAG = re.compile(r"[\[\(|#]\s*(es|esp|pt|ptbr|pt-br|br|fr|de|ger|it|tr|ru|pl|ar|jp|kr|nl)\s*[\]\)|]?",
                         re.IGNORECASE)
ENGLISH_TAG = re.compile(r"[\[\(|]\s*(en|eng|english)\s*[\]\)|]", re.IGNORECASE)


def _non_latin_letters(text: str) -> int:
    n = 0
    for ch in text:
        if ch.isalpha() and not ch.isascii():
            name = unicodedata.name(ch, "")
            if not name.startswith("LATIN"):
                n += 1
    return n


def looks_non_english(title: str) -> bool:
    if not title:
        return False
    if ENGLISH_TAG.search(title):
        return False
    letters = sum(ch.isalpha() for ch in title)
    if letters and _non_latin_letters(title) >= max(2, letters * 0.2):
        return True  # Cyrillic, Arabic, Japanese, Korean, ...
    tag = FOREIGN_TAG.search(title)
    if tag and not tag.group(0).strip().lower().startswith("#it"):  # "#it" is too ambiguous
        return True
    low = title.lower()
    words = re.findall(r"[\w'/]+", low)
    foreign = sum(w in FOREIGN_WORDS for w in words) + sum(p in low for p in FOREIGN_WORDS if " " in p)
    accented = sum(ch.isalpha() and not ch.isascii() for ch in title) > 0
    english = sum(w in ENGLISH_WORDS for w in words)
    return foreign + accented >= 2 and foreign + accented > english


NAMES = {"english": "en", "spanish": "es", "español": "es", "portuguese": "pt", "português": "pt",
         "french": "fr", "français": "fr", "german": "de", "deutsch": "de", "italian": "it", "russian": "ru",
         "turkish": "tr", "polish": "pl", "arabic": "ar", "japanese": "ja", "korean": "ko", "dutch": "nl",
         "chinese": "zh"}


def matches_language(lang: str | None, wanted: list[str]) -> bool | None:
    """True/False when the platform told us the language, None when it didn't."""
    if not wanted:
        return True
    if not lang or lang.lower() in ("other", "und", "zxx"):
        return None
    lang = NAMES.get(lang.strip().lower(), lang.strip().lower())
    return any(lang == w or lang.startswith(w + "-") or lang.startswith(w + "_") for w in wanted)
