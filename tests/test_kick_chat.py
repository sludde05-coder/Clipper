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
