import json

import pytest

from clipper.chat import youtube as yt

INITIAL = {
    "contents": {"liveChatRenderer": {
        "continuations": [{"invalidationContinuationData": {"continuation": "TOP", "timeoutMs": 10000}}],
        "header": {"liveChatHeaderRenderer": {"viewSelector": {"sortFilterSubMenuRenderer": {"subMenuItems": [
            {"title": "Top chat", "continuation": {"reloadContinuationData": {"continuation": "TOP"}}},
            {"title": "Live chat", "continuation": {"reloadContinuationData": {"continuation": "ALL"}}},
        ]}}}},
    }}
}

PAGE = ('<html><script>ytcfg.set({"INNERTUBE_API_KEY":"AIzaKEY","INNERTUBE_CONTEXT_CLIENT_VERSION":"2.2026"});'
        '</script><script>window["ytInitialData"] = ' + json.dumps(INITIAL) + ';</script></html>')


def test_page_parsing_picks_live_chat_not_top_chat():
    data = yt.extract_json(PAGE, "ytInitialData")
    assert yt.initial_continuation(data) == "ALL"
    assert yt.client_config(PAGE) == {"key": "AIzaKEY", "version": "2.2026"}


def test_var_style_page():
    page = "<script>var ytInitialData = " + json.dumps(INITIAL) + ";</script>"
    assert yt.initial_continuation(yt.extract_json(page, "ytInitialData")) == "ALL"


def test_no_chat_is_reported_clearly():
    with pytest.raises(yt.ChatUnavailable, match="no live chat"):
        yt.initial_continuation({"contents": {"twoColumnWatchNextResults": {}}})


def test_parse_actions():
    actions = [
        {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
            "authorName": {"simpleText": "@bob"}, "timestampUsec": "1763300000123456",
            "message": {"runs": [{"text": "NO WAY "}, {"emoji": {"emojiId": "😂", "shortcuts": [":joy:"]}}]}}}}},
        {"addChatItemAction": {"item": {"liveChatPaidMessageRenderer": {
            "authorName": {"simpleText": "@rich"}, "timestampUsec": "1763300001000000",
            "message": {"runs": [{"text": "W"}]}}}}},
        {"addChatItemAction": {"item": {"liveChatViewerEngagementMessageRenderer": {}}}},
        {"markChatItemAsDeletedAction": {}},
    ]
    msgs = yt.parse_actions(actions)
    assert [(m.user, m.text) for m in msgs] == [("@bob", "NO WAY :joy:"), ("@rich", "W")]
    assert msgs[0].ts == pytest.approx(1763300000.123456)


def test_next_continuation():
    conts = [{"timedContinuationData": {"continuation": "NEXT", "timeoutMs": 3000}}]
    assert yt._first_continuation(conts) == ("NEXT", 3000)


def test_video_id():
    assert yt.video_id("https://www.youtube.com/watch?v=0fOPjMD3Nn0") == "0fOPjMD3Nn0"
    assert yt.video_id("https://youtu.be/0fOPjMD3Nn0") == "0fOPjMD3Nn0"
    assert yt.video_id("https://www.youtube.com/live/0fOPjMD3Nn0?si=x") == "0fOPjMD3Nn0"
    assert yt.video_id("https://www.youtube.com/@someone/live") is None


def test_full_reader_against_fake_youtube(monkeypatch):
    """Connect, read two batches in order, and back off while chat is offline."""
    import asyncio
    import logging

    import aiohttp
    from aiohttp import web

    state = {"page_calls": 0, "polls": []}

    async def live_chat(request):
        state["page_calls"] += 1
        if state["page_calls"] == 1:  # first try: stream offline
            return web.Response(text="<script>var ytInitialData = {\"contents\": {}};</script>")
        return web.Response(text=PAGE)

    async def poll(request):
        body = await request.json()
        state["polls"].append(body["continuation"])
        assert request.query["key"] == "AIzaKEY"
        n = len(state["polls"])
        actions = [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
            "authorName": {"simpleText": f"u{n}{i}"}, "timestampUsec": "1763300000000000",
            "message": {"runs": [{"text": f"msg{n}{i}"}]}}}}} for i in range(2)]
        return web.json_response({"continuationContents": {"liveChatContinuation": {
            "actions": actions,
            "continuations": [{"timedContinuationData": {"continuation": f"C{n}", "timeoutMs": 500}}]}}})

    sleeps = []
    real_sleep = asyncio.sleep

    async def fast_sleep(s):
        sleeps.append(s)
        await real_sleep(0)

    async def go():
        app = web.Application()
        app.router.add_get("/live_chat", live_chat)
        app.router.add_post("/youtubei/v1/live_chat/get_live_chat", poll)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        monkeypatch.setattr(yt, "BASE", f"http://127.0.0.1:{port}")
        monkeypatch.setattr(yt.asyncio, "sleep", fast_sleep)
        got = []
        async with aiohttp.ClientSession() as s:
            async for m in yt.youtube_chat("https://www.youtube.com/watch?v=0fOPjMD3Nn0", s):
                got.append(m.text)
                if len(got) == 4:
                    break
        await runner.cleanup()
        return got

    logging.getLogger("clipper").setLevel(logging.DEBUG)
    got = asyncio.run(go())
    assert got == ["msg10", "msg11", "msg20", "msg21"]
    assert state["polls"][:2] == ["ALL", "C1"]   # "Live chat", then the token YouTube handed back
    assert sleeps[0] == 2                       # offline: waited before retrying
    assert 0.5 in sleeps                        # then polled at YouTube's suggested pace
