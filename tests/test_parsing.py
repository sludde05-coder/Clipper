from clipper.chat.twitch import parse_privmsg
from clipper.models import parse_target


def test_twitch_privmsg_with_tags():
    m = parse_privmsg("@badge-info=;display-name=Foo;id=x :foo!foo@foo.tmi.twitch.tv PRIVMSG #xqc :KEKW W :)")
    assert m.user == "foo" and m.text == "KEKW W :)"


def test_twitch_ignores_other_lines():
    assert parse_privmsg(":tmi.twitch.tv 001 justinfan1 :Welcome") is None


def test_targets():
    assert parse_target("twitch:XQC").url == "https://www.twitch.tv/xqc"
    assert parse_target("https://kick.com/AdinRoss").key == "kick:adinross"
    k = parse_target("kick:slug#12345")
    assert k.channel == "slug#12345" and k.url == "https://kick.com/slug"
    y = parse_target("https://www.youtube.com/watch?v=abcdefghijk")
    assert y.channel == "abcdefghijk"
    assert parse_target("https://youtu.be/abcdefghijk").channel == "abcdefghijk"



def test_streamer_links_in_any_shape():
    from clipper.models import parse_target
    assert parse_target("https://www.twitch.tv/KaiCenat").key == "twitch:kaicenat"
    assert parse_target("twitch.tv/kaicenat/videos").key == "twitch:kaicenat"
    assert parse_target("www.kick.com/adinross").key == "kick:adinross"
    yt = parse_target("https://www.youtube.com/@IShowSpeed")
    assert yt.key == "youtube:@ishowspeed" and yt.url == "https://www.youtube.com/@IShowSpeed/live"
    assert yt.display_name == "IShowSpeed"
    assert parse_target("youtube.com/@xQc/live").url == "https://www.youtube.com/@xQc/live"
    assert parse_target("https://www.youtube.com/watch?v=abcdefghijk").key == "youtube:abcdefghijk"
    import pytest
    for bad in ("https://www.twitch.tv/", "https://example.com/x", "https://www.youtube.com/feed/trending"):
        with pytest.raises(ValueError):
            parse_target(bad)
