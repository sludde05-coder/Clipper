import asyncio
import json
from pathlib import Path

import clipper.director as d


class FakeAnthropic:
    """Stands in for the API: returns queued answers and records each request."""
    answers: list = []
    requests: list = []

    def __init__(self, **k):
        outer = self

        class Messages:
            async def create(self, **kw):
                FakeAnthropic.requests.append(kw)
                text = json.dumps(FakeAnthropic.answers.pop(0))
                block = type("B", (), {"type": "text", "text": text})()
                return type("R", (), {"stop_reason": "end_turn", "content": [block]})()

        self.beta = type("Beta", (), {"messages": Messages()})()


def answer(hook):
    return {"hook": hook, "mood": "funny", "beats": [{"t": 25, "text": "wait for it"}], "emphasis": [],
            "crop_focus_x": 0.5, "post_caption": "lol #gta6"}


def run(monkeypatch, answers, recent=None):
    import anthropic
    FakeAnthropic.answers = list(answers)
    FakeAnthropic.requests = []
    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr(d, "_extract_frames", lambda *a, **k: [])
    meta = {"name": "Kai", "platform": "twitch", "explosion_offset": 30}
    return asyncio.run(d.claude_plan(Path("x.mp4"), meta, [], 50, "claude-haiku-5-5", recent=recent))


def test_chat_hook_gets_one_retry(monkeypatch):
    plan = run(monkeypatch, [answer("Chat roasts Kai"), answer("Kai trusted the wrong NPC")])
    assert plan.hook == "Kai trusted the wrong NPC"
    assert len(FakeAnthropic.requests) == 2
    retry = FakeAnthropic.requests[1]["messages"]
    assert retry[1]["role"] == "assistant" and "Chat roasts Kai" in retry[2]["content"]


def test_good_hook_needs_no_retry(monkeypatch):
    plan = run(monkeypatch, [answer("He really jumped the bridge")])
    assert plan.hook == "He really jumped the bridge" and len(FakeAnthropic.requests) == 1


def test_recent_hooks_are_in_the_prompt(monkeypatch):
    run(monkeypatch, [answer("Kai found a secret car")], recent=["POV: you trust the NPC", "He did NOT see that"])
    prompt = FakeAnthropic.requests[0]["messages"][0]["content"][-1]["text"]
    assert "POV: you trust the NPC" in prompt and "don't reuse their wording" in prompt
    assert "it is NOT the story" in prompt and "hook_options" in prompt


def test_hook_is_weak():
    assert d.hook_is_weak("Chat flames Kai", [])
    assert d.hook_is_weak("chat says he's washed", [])
    assert d.hook_is_weak("POV: you trust the cops", ["POV: you trust the NPC"])
    assert not d.hook_is_weak("Kai trusted the wrong NPC", ["POV: you trust the NPC"])
    assert not d.hook_is_weak("He chatted up the cop", [])   # only the word "chat"


def test_prompt_asks_for_the_clipper_headline_format():
    p = d.PROMPT.format(name="Kai", platform="twitch", title="t", length=30, offset=20, transcript="x", chat="c",
                        recent="", top_chat="KEKW")
    assert "Kai went on a date in GTA 6 😭" in p and "You can get a job in GTA 6?????" in p
    assert "NOT a description of the video" in p
    assert all(h.endswith(("😭", "😂", "💀", "🔥", "😳", "🥹", "💔", "?")) for hs in d.HOOKS.values() for h in hs)
