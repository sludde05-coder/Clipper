from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .detector import DetectorConfig


@dataclass
class DiscoveryConfig:
    game: str = "Grand Theft Auto VI"
    search_terms: list[str] = field(default_factory=lambda: ["GTA 6", "GTA VI", "Grand Theft Auto VI"])
    top_n: int = 10
    min_viewers: int = 500
    platforms: list[str] = field(default_factory=lambda: ["twitch", "youtube", "kick"])
    refresh_seconds: int = 300
    youtube_refresh_seconds: int = 900   # YouTube search costs 100 quota units
    always_track: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)                 # streamers never clipped, on any platform
    languages: list[str] = field(default_factory=lambda: ["en"])   # [] = any language


@dataclass
class ClipConfig:
    output_dir: str = "clips"
    buffer_dir: str = "buffer"
    pre_roll: int = 22        # seconds kept before the chat explosion
    post_roll: int = 8        # seconds kept after it (22 + 8 = a 30-second clip)
    chat_delay: int = 0       # extra seconds to shift the clip earlier
    segment_seconds: int = 2
    quality: str = "best"
    capture_before: int = 15      # extra seconds recorded before (and after) so the AI trim editor
    capture_after: int = 10       # can choose where the moment really starts and ends
    keep_originals: bool = False  # keep the 16:9 originals (in <Streamer>/Originals) after the phone version


@dataclass
class VerticalConfig:
    enabled: bool = True           # also render a 9:16 captioned version of each clip
    layout: str = "auto"           # "auto": webcam on top when there is one, else "blur"; or "facecam", "blur", "crop"
    ai_editors: bool = True        # the 5 AI editors (trim, webcam, captions, post text, review); needs ai_captions
    speech_captions: bool = True   # word-by-word captions from Whisper
    whisper_model: str = "small"   # tiny / base / small / medium / large-v3
    ai_captions: bool = True       # let Claude write the hook and reaction captions
    ai_model: str = "claude-opus-5-5"
    font: str = "Arial"
    crf: int = 21                  # quality: lower = better and bigger
    preset: str = "veryfast"
    max_parallel: int = 1          # renders at once (CPU heavy)


@dataclass
class PostConfig:
    folder: str = "POST"            # drop clips here to post them
    platforms: list[str] = field(default_factory=lambda: ["tiktok", "youtube", "instagram"])
    credit: bool = True             # name the streamer and platform in every caption
    autofill: bool = True           # Post fills in the upload page in Clipper's browser window
    autosubmit: bool = False        # ...and clicks Post / Publish / Share too (against the sites' rules: account risk)
    pause_between_clips: int = 120  # seconds between clips when posting by itself, so it doesn't look like a bot
    tiktok_account: str = ""        # shown in the app, e.g. "@myclips"
    youtube_account: str = ""
    instagram_account: str = ""
    tiktok_tags: str = ""           # extra hashtags added to every caption on that platform
    youtube_tags: str = ""
    instagram_tags: str = ""


@dataclass
class PhoneConfig:
    enabled: bool = True            # serve the phone app while the clipper runs
    port: int = 8765
    key: str = ""                   # secret in the QR code; made automatically on first start
    public_url: str = ""            # optional, e.g. a Tailscale https:// address (see SETUP.md)


@dataclass
class Credentials:
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    youtube_api_key: str = ""
    kick_client_id: str = ""
    kick_client_secret: str = ""
    kick_category_id: int = 0
    kick_pusher_key: str = "32cbd69e4b950bf97679"
    kick_pusher_cluster: str = "us2"


@dataclass
class Config:
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    clips: ClipConfig = field(default_factory=ClipConfig)
    vertical: VerticalConfig = field(default_factory=VerticalConfig)
    post: PostConfig = field(default_factory=PostConfig)
    phone: PhoneConfig = field(default_factory=PhoneConfig)
    creds: Credentials = field(default_factory=Credentials)


def _fill(obj, data: dict, prefix: str = ""):
    names = {f.name for f in fields(obj)}
    for k, v in data.items():
        name = prefix + k
        if name in names:
            setattr(obj, name, v)


def load_config(path: str | None) -> Config:
    cfg = Config()
    if path and Path(path).exists():
        data = tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))
        _fill(cfg.discovery, data.get("discovery", {}))
        _fill(cfg.detector, data.get("detector", {}))
        _fill(cfg.clips, data.get("clips", {}))
        _fill(cfg.vertical, data.get("vertical", {}))
        _fill(cfg.post, data.get("post", {}))
        _fill(cfg.phone, data.get("phone", {}))
        for platform in ("twitch", "youtube", "kick"):
            _fill(cfg.creds, data.get(platform, {}), prefix=platform + "_")
        # The Anthropic SDK reads its key from the environment; let the file supply it.
        key = data.get("anthropic", {}).get("api_key", "")
        if key and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = key
    # Environment variables win, so secrets can stay out of the file.
    for f in fields(cfg.creds):
        env = os.environ.get(f.name.upper())
        if env:
            setattr(cfg.creds, f.name, type(getattr(cfg.creds, f.name))(env))
    return cfg
