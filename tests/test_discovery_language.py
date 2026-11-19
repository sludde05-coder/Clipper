import asyncio

from clipper.config import Config
from clipper.discovery import Discovery


class FakeResp:
    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    async def json(self, **k):
        return self.data


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **k):
        return FakeResp({"access_token": "t", "expires_in": 3600})

    def get(self, url, params=None, **k):
        self.calls.append((url, params))
        if url.endswith("/games"):
            return FakeResp({"data": [{"id": "42"}]})
        if url.endswith("/helix/streams"):
            return FakeResp({"data": [
                {"user_login": "en1", "user_name": "En1", "viewer_count": 9000, "title": "GTA 6 day one", "language": "en"},
                {"user_login": "es1", "user_name": "Es1", "viewer_count": 8000, "title": "GTA 6", "language": "es"},
            ]})
        if url.endswith("/search"):
            return FakeResp({"items": [{"id": {"videoId": v}} for v in ("ytEN", "ytBR", "ytLBL")]})
        if url.endswith("/videos"):
            return FakeResp({"items": [
                {"id": "ytEN", "snippet": {"title": "GTA 6 IS HERE", "channelId": "a"},
                 "liveStreamingDetails": {"concurrentViewers": "7000"}},
                {"id": "ytBR", "snippet": {"title": "JOGANDO GTA 6 AO VIVO", "channelId": "b"},
                 "liveStreamingDetails": {"concurrentViewers": "6000"}},
                {"id": "ytLBL", "snippet": {"title": "GTA 6 stream", "channelId": "c", "defaultAudioLanguage": "fr"},
                 "liveStreamingDetails": {"concurrentViewers": "5000"}},
            ]})
        if url.endswith("/categories"):
            return FakeResp({"data": [{"id": 7, "name": "Grand Theft Auto VI"}]})
        if url.endswith("/livestreams"):
            return FakeResp({"data": [
                {"slug": "kickEN", "viewer_count": 4000, "stream_title": "GTA 6", "language": "English"},
                {"slug": "kickTR", "viewer_count": 3000, "stream_title": "GTA 6", "language": "Turkish"},
                {"slug": "kickNONE", "viewer_count": 2000, "stream_title": "GTA 6 EN VIVO con los pibes"},
            ]})
        raise AssertionError(url)


def run(languages):
    cfg = Config()
    cfg.discovery.languages = languages
    cfg.creds.twitch_client_id = cfg.creds.twitch_client_secret = "x"
    cfg.creds.youtube_api_key = "x"
    cfg.creds.kick_client_id = cfg.creds.kick_client_secret = "x"
    s = FakeSession()
    top = asyncio.run(Discovery(cfg, s).top_streams())
    return [t.channel for t in top], s


def test_english_only():
    names, s = run(["en"])
    assert names == ["en1", "ytEN", "kicken"]
    twitch_params = next(p for u, p in s.calls if u.endswith("/helix/streams"))
    assert ("language", "en") in twitch_params


def test_any_language():
    names, _ = run([])
    assert set(names) == {"en1", "es1", "ytEN", "ytBR", "ytLBL", "kicken", "kicktr", "kicknone"}


def test_multistreamer_is_clipped_once_on_the_bigger_stream():
    from clipper.discovery import one_per_streamer, person_key
    from clipper.models import Stream
    streams = [
        Stream("twitch", "xqc", "u", 60000, "", "xQc"),
        Stream("kick", "xqc", "u", 45000, "", "xqc"),
        Stream("youtube", "vid1", "u", 9000, "", "KaiCenat Live"),
        Stream("twitch", "kaicenat", "u", 80000, "", "KaiCenat"),
        Stream("twitch", "ttvlacy", "u", 5000, "", "TTVLacy"),
        Stream("youtube", "vid2", "u", 7000, "", "Lacy"),
        Stream("twitch", "jynxzi", "u", 30000, "", "Jynxzi"),
    ]
    kept = sorted(s.key for s in one_per_streamer(streams))
    assert kept == ["twitch:jynxzi", "twitch:kaicenat", "twitch:xqc", "youtube:vid2"]
    assert person_key(Stream("twitch", "ttv", "u", 1, "", "")) == "ttv"            # never stripped to nothing


def test_blocked_streamers_are_skipped_on_every_platform():
    cfg = Config()
    cfg.discovery.languages = []
    cfg.discovery.top_n = 2
    cfg.discovery.blocked = ["En1", "ytBR"]   # by name; "ytBR" is a YouTube video id here, matched as a name too
    cfg.creds.twitch_client_id = cfg.creds.twitch_client_secret = "x"
    cfg.creds.youtube_api_key = "x"
    cfg.creds.kick_client_id = cfg.creds.kick_client_secret = "x"
    top = asyncio.run(Discovery(cfg, FakeSession()).top_streams())
    # en1 (9000 viewers) is blocked, so the next two biggest take the top 2
    assert [t.channel for t in top] == ["es1", "ytEN"]



class KickV2Session(FakeSession):
    """Kick's current API: v1 is retired (404); v2 names fields differently."""
    def __init__(self, category_name="Grand Theft Auto VI"):
        super().__init__()
        self.category_name = category_name

    def get(self, url, params=None, **k):
        self.calls.append((url, params))
        if "/public/v1/" in url:
            r = FakeResp({"message": "Not Found"})
            r.status = 404

            async def text():
                return "Not Found"
            r.text = text
            return r
        if url.endswith("/v2/categories"):
            return FakeResp({"data": [{"id": 11, "name": "Grand Theft Auto V"}, {"id": 99, "name": self.category_name}]})
        if url.endswith("/v2/livestreams"):
            cat = {"id": 99, "name": self.category_name}
            return FakeResp({"data": [
                {"broadcaster_user": {"username": "AdinRoss"}, "channel": {"slug": "adinross"}, "language_code": "en",
                 "title": "GTA 6 DAY 1", "viewer_count": 52000, "category": cat},
                {"broadcaster_user": {"username": "Wrong"}, "channel": {"slug": "wrong"}, "language_code": "en",
                 "title": "gta 5 rp", "viewer_count": 90000, "category": {"id": 11, "name": "Grand Theft Auto V"}},
                {"broadcaster_user": {"username": "Turk"}, "channel": {"slug": "turk"}, "language_code": "tr",
                 "title": "GTA 6", "viewer_count": 30000, "category": cat},
            ], "pagination": {"next_cursor": ""}})
        return super().get(url, params, **k)


def kick_only(session):
    cfg = Config()
    cfg.discovery.platforms = ["kick"]
    cfg.creds.kick_client_id = cfg.creds.kick_client_secret = "x"
    return asyncio.run(Discovery(cfg, session).top_streams())


def test_kick_uses_the_current_api():
    s = KickV2Session()
    top = kick_only(s)
    assert [(t.channel, t.viewers, t.display_name) for t in top] == [("adinross", 52000, "AdinRoss")]
    assert not any("/v1/" in u for u, _ in s.calls)          # v2 answered, so the retired v1 isn't used
    assert ("category_id", "99") in s.calls[-1][1]


def test_kick_category_named_differently_still_matches():
    assert [t.channel for t in kick_only(KickV2Session("GTA VI"))] == ["adinross"]


def test_old_kick_api_still_works_as_a_fallback():
    s = FakeSession()          # answers only the old v1 shapes at the paths the v2 calls also end with
    top = kick_only(s)
    assert [t.channel for t in top] == ["kicken"]
