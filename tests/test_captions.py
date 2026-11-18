from clipper.captions import build_ass, clean, group_words
from clipper.director import Beat, Plan, chat_mood, rule_plan
from clipper.transcribe import Word


def words(text, start=0.0, step=0.3):
    return [Word(start + i * step, start + i * step + 0.25, w) for i, w in enumerate(text.split())]


def test_chat_mood():
    assert chat_mood(["KEKW", "LMAOOO", "OMEGALUL OMEGALUL", "W"])[0] == "funny"
    assert chat_mood(["WWWW", "LETS GO", "POGGERS", "W"])[0] == "hype"
    assert chat_mood(["WTF", "???", "NO WAY", "huh"])[0] == "shock"


def test_rule_plan_uses_chat_mood_but_not_chat_words():
    meta = {"name": "Kai", "platform": "twitch", "explosion_offset": 30,
            "chat_timeline": [[30.1, "a", "KEKW"], [30.2, "b", "KEKW"], [30.3, "c", "LMAO"]]}
    hooks = {rule_plan(meta, []).hook for _ in range(40)}
    assert len(hooks) > 2                                   # varied, not one template
    assert all("chat" not in h.lower() for h in hooks)
    p = rule_plan(meta, [])
    assert p.mood == "funny"
    assert p.beats and p.beats[0].text in ("WAIT FOR IT", "WATCH THIS", "HERE IT COMES") and p.beats[0].t < 30
    assert "gta 6" in p.post_caption and "#gta6" in p.post_caption       # searchable, natural


def test_grouping_breaks_on_pause_and_punctuation():
    ws = words("one two three four") + words("five", start=5) + [Word(6, 6.2, "end."), Word(6.3, 6.5, "next")]
    groups = [[w.text for w in g] for g in group_words(ws)]
    assert groups == [["one", "two", "three"], ["four"], ["five"], ["end."], ["next"]]


def test_ass_has_all_layers_and_strips_emoji():
    plan = Plan(hook="He did WHAT 😱 {x}", mood="shock", beats=[Beat(3, "NO WAY 🚓")], emphasis=["bridge"])
    ass = build_ass(plan, words("jump the bridge now"), 10.0)
    assert "He did WHAT x" in ass and "😱" not in ass and "🚓" not in ass
    assert ass.count(",Speech,") == 4           # one event per spoken word
    assert ",Beat,," in ass and "NO WAY" in ass
    assert "&H00303BFF" in ass                  # shock red as ASS &HAABBGGRR


def test_clean():
    assert clean("a{b}\\c 🔥\n d") == "abc d"


def test_fallback_quotes_the_streamer_when_it_can():
    from clipper.director import best_quote
    from clipper.transcribe import Word
    words = [Word(i, i + 0.3, w) for i, w in enumerate("okay let me try this. why is he in my house?! no way".split())]
    assert best_quote(words) == "why is he in my house?!"
    assert best_quote([]) == ""


def test_stock_phrases_get_rewritten():
    from clipper.director import hook_is_weak
    assert hook_is_weak("This might be the play of the day", [])
    assert hook_is_weak("He pulls up the GTA 6 map and goes silent", [])
    assert not hook_is_weak("he was NOT ready for that jump", [])


def test_swear_words_are_bleeped_everywhere_on_screen():
    from clipper.captions import BLEEP, censor
    assert BLEEP == "*#@*"
    assert censor("what the fuck!") == "what the *#@*!"
    assert censor("oh shiiit, MOTHERFUCKER") == "oh *#@*, *#@*"
    assert censor("that was f***ing crazy") == "that was *#@* crazy"      # already starred by the transcript
    for fine in ("class pass grass", "assassin", "shiitake", "Scunthorpe", "hit the bass", "cocktail"):
        assert censor(fine) == fine
    plan = Plan(hook="he said fuck it", mood="shock", beats=[Beat(3, "HOLY SHIT")])
    ass = build_ass(plan, words("what the fuck bro"), 10.0)
    assert "FUCK" not in ass and "SHIT" not in ass
    assert "he said *#@* it" in ass and "HOLY *#@*" in ass and ass.count("*#@*") >= 4


def test_spoken_word_groups_never_overlap():
    """Two groups on screen at once draw over each other ("YOU'LL" + "WE'LL HELP" jumbled)."""
    import re
    ws = [Word(0.0, 0.3, "you'll"), Word(0.3, 0.6, "see."), Word(0.65, 0.9, "we'll"), Word(0.9, 1.2, "help")]
    ass = build_ass(Plan(hook="", mood="hype"), ws, 5.0)
    def sec(s):
        h, m, x = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(x)
    spans = sorted((sec(a), sec(b)) for a, b in re.findall(r"Dialogue: 1,([^,]+),([^,]+),Speech", ass))
    assert len(spans) == 4
    assert all(spans[i][1] <= spans[i + 1][0] + 1e-6 for i in range(len(spans) - 1)), spans


def test_headline_is_drawn_with_its_emoji(tmp_path):
    """The headline is a picture so it can end in a colour emoji; swears are still bleeped."""
    from PIL import Image

    from clipper import headline
    if headline._fonts()[1] is None:
        import pytest
        pytest.skip("no colour emoji font on this computer")
    with_emoji = headline.render("Kai went on a date 😭", tmp_path / "a.png")
    without = headline.render("Kai went on a date", tmp_path / "b.png")
    assert with_emoji and without and with_emoji[0] > without[0]       # the emoji takes room
    img = Image.open(tmp_path / "a.png").convert("RGBA")
    colours = {px[:3] for px in img.getdata() if px[3] == 255 and px[:3] not in ((255, 255, 255),)}
    assert any(r > 200 and g > 150 and b < 120 for r, g, b in colours)  # the yellow of 😭
    # a long one wraps onto more lines instead of running off the screen
    long = headline.render("TheBurntPeanut got hit on by a few older women at the bar in GTA 6 😭", tmp_path / "c.png")
    assert long[0] <= headline.MAX_WIDTH and long[1] > with_emoji[1]
    plan = Plan(hook="what the fuck 😭", mood="funny")
    from clipper.captions import censor
    assert censor(plan.hook) == "what the *#@* 😭"
