"""Kick chat-room numbers: remembered, and read from the channel page pasted as text."""
import asyncio

from clipper.chat import kick


class Refused:
    status = 403

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class Session:
    closed = False

    def __init__(self):
        self.asked = 0

    def get(self, *a, **k):
        self.asked += 1
        return Refused()


def test_room_number_from_a_pasted_page_or_number():
    page = '{"id":668,"user_id":676,"slug":"adinross","chatroom":{"id":668,"chatable_type":"App\\\\Models\\\\Channel"},"x":1}'
    assert kick.room_from_text(page) == 668
    assert kick.room_from_text("  123456 ") == 123456
    assert kick.room_from_text('{"chatroom_id": 42}') == 42
    assert kick.room_from_text("nothing here") is None


def test_known_rooms_skip_the_kick_com_lookup():
    kick.ROOMS.clear()
    kick.load_rooms(["AdinRoss#668", "bad", "x#notanumber"])
    assert kick.ROOMS == {"adinross": 668}
    s = Session()
    assert asyncio.run(kick.chatroom_id("adinross", s)) == 668 and s.asked == 0


def test_refused_lookup_asks_for_the_number():
    kick.ROOMS.clear()
    s = Session()
    try:
        asyncio.run(kick.chatroom_id("someone", s))
        raise AssertionError("should have asked for the number")
    except kick.NeedsRoom:
        pass



class Resp:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(self.status)

    async def json(self, **k):
        return self.data


class KeySession:
    closed = False

    def __init__(self, answer, status=200):
        self.answer, self.status, self.posts = answer, status, []

    def post(self, url, json=None, **k):
        self.posts.append((url, json))
        return Resp(self.answer, self.status)


def test_kicks_current_chat_key_is_looked_up():
    from clipper.config import Credentials
    kick._live_creds = None
    s = KeySession({"data": {"connections": [
        {"provider": "centrifugo", "credentials": {"url": "wss://x"}},
        {"provider": "pusher", "credentials": {"app_key": "newkey123456", "cluster": "us2"}}]}})
    assert asyncio.run(kick.pusher_creds(s, Credentials())) == ("newkey123456", "us2")
    url, body = s.posts[0]
    assert url == "https://web.kick.com/api/v1/realtime/connection"
    assert body["capabilities"]["accepted_providers"] == [{"provider": "pusher"}]
    # asked once, then remembered
    asyncio.run(kick.pusher_creds(s, Credentials()))
    assert len(s.posts) == 1


def test_retired_key_in_config_isnt_used_when_the_lookup_fails():
    from clipper.config import Credentials
    kick._live_creds = None
    old = Credentials(kick_pusher_key="32cbd69e4b950bf97679")
    assert asyncio.run(kick.pusher_creds(KeySession({}, status=500), old)) == (kick.CURRENT_KEY, "us2")
    kick._live_creds = None
    # a key that isn't plain letters/digits (or a strange cluster) is never put in the address
    bad = KeySession({"data": {"connections": [{"provider": "pusher", "credentials": {"app_key": "x/../y", "cluster": "us2"}}]}})
    assert asyncio.run(kick.pusher_creds(bad, Credentials()))[0] == kick.CURRENT_KEY


def test_a_challenge_page_instead_of_data_asks_for_the_number():
    class Page(Refused):
        status = 200

        def raise_for_status(self):
            pass

        async def json(self, **k):
            raise ValueError("not json")

    class S(Session):
        def get(self, *a, **k):
            return Page()
    kick.ROOMS.clear()
    try:
        asyncio.run(kick.chatroom_id("someone_else", S()))
        raise AssertionError("should have asked for the number")
    except kick.NeedsRoom:
        pass
