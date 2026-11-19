from __future__ import annotations

import re
from urllib.parse import urlparse
from dataclasses import dataclass, field
import time


@dataclass(frozen=True)
class Stream:
    platform: str        # "twitch" | "youtube" | "kick"
    channel: str         # login / slug / YouTube video id
    url: str
    viewers: int = 0
    title: str = ""
    display_name: str = ""

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.channel}"


@dataclass
class ChatMessage:
    user: str
    text: str
    ts: float = field(default_factory=time.time)


def parse_target(spec: str) -> Stream:
    """Turn 'twitch:xqc', 'kick:adinross', 'youtube:VIDEOID' or a URL into a Stream."""
    s = spec.strip().strip("<>\"'")
    low = s.lower()
    if re.match(r"^(www\.|m\.)?(twitch\.tv|kick\.com|youtube\.com|youtu\.be)/", low):
        s, low = "https://" + s, "https://" + low          # pasted without https://
    if low.startswith("http"):
        path = [p for p in urlparse(s).path.split("/") if p]
        if "twitch.tv/" in low:
            if not path:
                raise ValueError(f"That Twitch link has no channel in it: {spec}")
            return parse_target("twitch:" + path[0])
        if "kick.com/" in low:
            if not path:
                raise ValueError(f"That Kick link has no channel in it: {spec}")
            return parse_target("kick:" + path[0])
        if "youtube.com" in low or "youtu.be" in low:
            vid = _youtube_id(s)
            if vid:
                return Stream("youtube", vid, f"https://www.youtube.com/watch?v={vid}")
            # A channel (youtube.com/@name, /channel/ID, /c/name): its /live page is whatever it streams now.
            if path and (path[0].startswith("@") or path[0] in ("channel", "c", "user")):
                handle = path[0] if path[0].startswith("@") else "/".join(path[:2])
                name = path[0][1:] if path[0].startswith("@") else path[1] if len(path) > 1 else path[0]
                return Stream("youtube", handle.lower(), f"https://www.youtube.com/{handle}/live", display_name=name)
            raise ValueError(f"Use a YouTube channel link (youtube.com/@name) or a live video link: {spec}")
        raise ValueError(f"Only Twitch, Kick and YouTube links work: {spec}")
    if ":" not in s:
        raise ValueError(f"Use platform:channel, got {spec!r}")
    platform, channel = s.split(":", 1)
    platform = platform.lower()
    if platform == "twitch":
        channel = channel.lower()
        return Stream("twitch", channel, f"https://www.twitch.tv/{channel}")
    if platform == "kick":
        channel = channel.lower()  # may carry a chatroom id: "slug#123456"
        return Stream("kick", channel, f"https://kick.com/{channel.split('#')[0]}")
    if platform in ("youtube", "yt"):
        return Stream("youtube", channel, f"https://www.youtube.com/watch?v={channel}")
    raise ValueError(f"Unknown platform {platform!r} (use twitch, youtube or kick)")


def _youtube_id(url: str) -> str | None:  # noqa: C901
    from urllib.parse import urlparse, parse_qs
    u = urlparse(url)
    if u.netloc.endswith("youtu.be"):
        return u.path.strip("/") or None
    if "v" in parse_qs(u.query):
        return parse_qs(u.query)["v"][0]
    parts = u.path.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "live":
        return parts[1]
    return None
