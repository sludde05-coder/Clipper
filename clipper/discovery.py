"""Finds the biggest live streams for a game across Twitch, YouTube and Kick.

  Twitch  – Helix API, streams in the game's category, sorted by viewers.
  YouTube – Data API search for live videos matching the search terms, then
            concurrent viewer counts. Each search costs 100 of the default
            10,000 daily quota units, hence the slower refresh.
  Kick    – Public API (v2; the older v1 endpoints are only a fallback since Kick
            retired them), livestreams in the game's category, biggest first.

Only streams in the configured languages are kept (default: English). Twitch and
Kick label each stream's language; YouTube often doesn't, so there the title
is checked for signs of another language.

A platform without credentials is skipped with a warning.
"""
from __future__ import annotations

import logging
import re
import time

import aiohttp

from .config import Config
from .language import looks_non_english, matches_language
from .models import Stream, parse_target

log = logging.getLogger(__name__)
APP_UA = {"User-Agent": "Clipper/1.0 (+https://github.com/sludde05-coder/clipper)"}


KICK_API = "https://api.kick.com/public"
_ROMAN = {"vi": "6", "v": "5", "iv": "4"}


def game_key(name: str) -> str:
    """A game name boiled down for matching: 'Grand Theft Auto VI', 'GTA VI' and 'GTA 6' -> 'gta6'."""
    k = re.sub(r"[^a-z0-9]", "", (name or "").lower()).replace("grandtheftauto", "gta")
    if k.startswith("gta") and k[3:] in _ROMAN:
        k = "gta" + _ROMAN[k[3:]]
    return k


class KickError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(f"Kick said {status}: {text}" if text else f"Kick said {status}")
        self.status = status


_AFFIX = re.compile(r"^(ttv|yt)+|(live|tv|ttv|yt|official|irl)+$")


def person_key(st: Stream) -> str:
    """Who is streaming, the same on every platform: 'xQc' (Twitch) and 'xQc Live' (YouTube) -> 'xqc'."""
    name = (st.display_name or st.channel) if st.platform == "youtube" else st.channel
    return name_key(name) or st.key


def name_key(name: str) -> str:
    """A streamer name boiled down for matching: lowercase letters and digits, without 'ttv', 'live', 'tv'..."""
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower().split("#")[0].split(":")[-1])
    for _ in range(3):  # strip "ttv", "live", "tv" ... from either end
        shorter = _AFFIX.sub("", key)
        if len(shorter) < 3 or shorter == key:
            break
        key = shorter
    return key


def one_per_streamer(streams) -> list[Stream]:
    """Someone streaming on two platforms at once is clipped once: on the stream with the most viewers."""
    best: dict[str, Stream] = {}
    for st in streams:
        k = person_key(st)
        if k not in best or st.viewers > best[k].viewers:
            if k in best:
                log.info("%s is also live on %s with fewer viewers: clipping only %s",
                         st.display_name or st.channel, best[k].platform, st.key)
            best[k] = st
        else:
            log.info("%s is also live on %s with fewer viewers: clipping only %s",
                     st.display_name or st.channel, st.platform, best[k].key)
    return list(best.values())


class Discovery:
    def __init__(self, cfg: Config, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.s = session
        self._twitch_token: tuple[str, float] | None = None
        self._kick_token: tuple[str, float] | None = None
        self._twitch_game_id: str | None = None
        self._kick_category_id: int | None = cfg.creds.kick_category_id or None
        self._yt_cache: tuple[float, list[Stream]] = (0.0, [])
        self._warned: set[str] = set()
        # What each platform found last time, for the app: {platform: {"found", "in_top", "biggest", "error"}}
        self.status: dict[str, dict] = {}

    def _warn_once(self, key: str, msg: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg)

    async def top_streams(self) -> list[Stream]:
        d = self.cfg.discovery
        found: list[Stream] = []
        counts: dict[str, int] = {}
        status: dict[str, dict] = {}
        c = self.cfg.creds
        has_key = {"twitch": bool(c.twitch_client_id and c.twitch_client_secret), "youtube": bool(c.youtube_api_key),
                   "kick": bool(c.kick_client_id and c.kick_client_secret)}
        for platform, fn in (("twitch", self._twitch), ("youtube", self._youtube), ("kick", self._kick)):
            if platform not in d.platforms:
                continue
            if not has_key[platform]:
                status[platform] = {"error": "no key"}
                continue
            try:
                got = await fn()
                counts[platform] = len(got)
                found += got
                top = max(got, key=lambda s: s.viewers) if got else None
                status[platform] = {"found": len(got), "error": None,
                                    "biggest": [top.display_name or top.channel, top.viewers] if top else None}
            except Exception as e:  # noqa: BLE001
                log.warning("%s discovery failed: %s", platform, e)
                status[platform] = {"error": str(e)[:200]}
        best: dict[str, Stream] = {}
        for st in found:
            if st.viewers >= d.min_viewers and st.viewers > best.get(st.key, Stream("", "", "")).viewers:
                best[st.key] = st
        blocked = {name_key(b) for b in d.blocked if name_key(b)}
        allowed = [s for s in best.values() if person_key(s) not in blocked and name_key(s.display_name) not in blocked]
        everyone = sorted(one_per_streamer(allowed), key=lambda s: s.viewers, reverse=True)
        # Kick streams are often smaller than Twitch's, so a few spots are kept for the biggest ones.
        kept = [s for s in everyone if s.platform == "kick"][: max(0, min(d.kick_spots, d.top_n))]
        rest = [s for s in everyone if s not in kept][: d.top_n - len(kept)]
        ranked = sorted(kept + rest, key=lambda s: s.viewers, reverse=True)
        for p, st in status.items():
            if "found" in st:
                st["in_top"] = sum(1 for s in ranked if s.platform == p)
        self.status = status
        self._report(counts, found, ranked)
        pinned = [parse_target(t) for t in d.always_track]
        keys = {s.key for s in ranked}
        return ranked + [p for p in pinned if p.key not in keys]

    def _report(self, counts: dict[str, int], found: list[Stream], ranked: list[Stream]) -> None:
        """Say what each platform found, and why a platform's streams didn't make the top (if they didn't)."""
        summary = ", ".join(f"{p.capitalize()} {n}" for p, n in counts.items())
        if summary and summary != getattr(self, "_last_summary", None):
            self._last_summary = summary
            log.info("🔎 live %s streams found: %s", self.cfg.discovery.game, summary)
        if counts.get("kick") and ranked and not any(s.platform == "kick" for s in ranked):
            biggest = max((s for s in found if s.platform == "kick"), key=lambda s: s.viewers)
            note = (f"Kick's biggest {self.cfg.discovery.game} stream ({biggest.display_name or biggest.channel}, "
                    f"{biggest.viewers:,} viewers) is smaller than the top {len(ranked)} "
                    f"(smallest there: {ranked[-1].viewers:,})")
            if note != getattr(self, "_last_kick_note", None):
                self._last_kick_note = note
                log.info("ℹ️  %s, so no Kick streams are clipped right now", note)

    # ---------- Twitch ----------
    async def _twitch_headers(self) -> dict[str, str] | None:
        c = self.cfg.creds
        if not (c.twitch_client_id and c.twitch_client_secret):
            self._warn_once("twitch", "Twitch credentials missing: skipping Twitch discovery")
            return None
        if not self._twitch_token or self._twitch_token[1] < time.time() + 60:
            async with self.s.post("https://id.twitch.tv/oauth2/token", params={
                "client_id": c.twitch_client_id, "client_secret": c.twitch_client_secret,
                "grant_type": "client_credentials"}) as r:
                r.raise_for_status()
                j = await r.json()
            self._twitch_token = (j["access_token"], time.time() + j["expires_in"])
        return {"Client-Id": c.twitch_client_id, "Authorization": f"Bearer {self._twitch_token[0]}"}

    async def _twitch(self) -> list[Stream]:
        h = await self._twitch_headers()
        if not h:
            return []
        api = "https://api.twitch.tv/helix"
        if not self._twitch_game_id:
            async with self.s.get(f"{api}/games", params={"name": self.cfg.discovery.game}, headers=h) as r:
                r.raise_for_status()
                data = (await r.json())["data"]
            if not data:
                self._warn_once("twitch-game", f"Twitch has no category named {self.cfg.discovery.game!r} yet")
                return []
            self._twitch_game_id = data[0]["id"]
        langs = self.cfg.discovery.languages
        params = [("game_id", self._twitch_game_id), ("first", "100"), *(("language", l) for l in langs)]
        async with self.s.get(f"{api}/streams", params=params, headers=h) as r:
            r.raise_for_status()
            data = (await r.json())["data"]
        return [Stream("twitch", s["user_login"], f"https://www.twitch.tv/{s['user_login']}",
                       s["viewer_count"], s["title"], s["user_name"]) for s in data
                if matches_language(s.get("language"), langs) is True
                or (matches_language(s.get("language"), langs) is None
                    and not ("en" in langs and looks_non_english(s["title"])))]

    # ---------- YouTube ----------
    async def _youtube(self) -> list[Stream]:
        key = self.cfg.creds.youtube_api_key
        if not key:
            self._warn_once("youtube", "YouTube API key missing: skipping YouTube discovery")
            return []
        cached_at, cached = self._yt_cache
        if time.time() - cached_at < self.cfg.discovery.youtube_refresh_seconds:
            return cached
        api = "https://www.googleapis.com/youtube/v3"
        langs = self.cfg.discovery.languages
        q = "|".join(f'"{t}"' for t in self.cfg.discovery.search_terms)
        async with self.s.get(f"{api}/search", params={
            "part": "snippet", "eventType": "live", "type": "video", "q": q,
            "order": "viewCount", "maxResults": 50, "key": key,
            **({"relevanceLanguage": langs[0]} if len(langs) == 1 else {})}) as r:
            r.raise_for_status()
            items = (await r.json()).get("items", [])
        ids = [i["id"]["videoId"] for i in items]
        if not ids:
            self._yt_cache = (time.time(), [])
            return []
        async with self.s.get(f"{api}/videos", params={
            "part": "snippet,liveStreamingDetails", "id": ",".join(ids), "key": key}) as r:
            r.raise_for_status()
            videos = (await r.json()).get("items", [])
        terms = [t.lower() for t in self.cfg.discovery.search_terms]
        by_channel: dict[str, Stream] = {}
        for v in videos:
            sn = v["snippet"]
            title = sn.get("title", "").lower()
            if not any(t in title for t in terms):
                continue  # search is fuzzy; keep only streams whose title names the game
            # YouTube's language fields are often empty; then judge by the title.
            lang_ok = matches_language(sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"), langs)
            if lang_ok is False or (lang_ok is None and "en" in langs and looks_non_english(sn.get("title", ""))):
                continue
            viewers = int(v.get("liveStreamingDetails", {}).get("concurrentViewers", 0))
            st = Stream("youtube", v["id"], f"https://www.youtube.com/watch?v={v['id']}",
                        viewers, sn.get("title", ""), sn.get("channelTitle", ""))
            ch = sn.get("channelId", v["id"])
            if ch not in by_channel or viewers > by_channel[ch].viewers:
                by_channel[ch] = st
        result = list(by_channel.values())
        self._yt_cache = (time.time(), result)
        return result

    # ---------- Kick ----------
    async def _kick_headers(self) -> dict[str, str] | None:
        c = self.cfg.creds
        if not (c.kick_client_id and c.kick_client_secret):
            self._warn_once("kick", "Kick credentials missing: skipping Kick discovery")
            return None
        if not self._kick_token or self._kick_token[1] < time.time() + 60:
            async with self.s.post("https://id.kick.com/oauth/token", headers=APP_UA, data={
                "grant_type": "client_credentials", "client_id": c.kick_client_id,
                "client_secret": c.kick_client_secret}) as r:
                r.raise_for_status()
                j = await r.json()
            self._kick_token = (j["access_token"], time.time() + j.get("expires_in", 3600))
        return {**APP_UA, "Authorization": f"Bearer {self._kick_token[0]}", "Accept": "application/json"}

    async def _kick_get(self, path: str, params, headers: dict) -> dict:
        async with self.s.get(f"{KICK_API}{path}", params=params, headers=headers) as r:
            status = getattr(r, "status", 200)
            if status >= 400:
                try:
                    text = (await r.text())[:160]
                except Exception:  # noqa: BLE001
                    text = ""
                raise KickError(status, " ".join(text.split()))
            return await r.json(content_type=None) or {}

    def _kick_wanted(self) -> set[str]:
        d = self.cfg.discovery
        return {k for k in (game_key(n) for n in [d.game, *d.search_terms]) if k}

    async def _kick_category(self, h: dict) -> int | None:
        """The game's category id on Kick: by name (v2), by search (old v1), or from a live stream in it."""
        d = self.cfg.discovery
        want, names = self._kick_wanted(), [d.game, *d.search_terms]
        pick = lambda cats: next((c for c in cats if game_key(c.get("name", "")) in want), None)  # noqa: E731
        tries = [("/v2/categories", [("name", ",".join(names)), ("limit", "100")])]
        tries += [("/v1/categories", {"q": n}) for n in names]
        errors = []
        for path, params in tries:
            try:
                match = pick((await self._kick_get(path, params, h)).get("data") or [])
            except KickError as e:
                errors.append(str(e))
                continue
            if match:
                return int(match["id"])
        # Last resort: the biggest live streams on Kick say which category they're in.
        try:
            live = (await self._kick_get("/v2/livestreams", [("limit", "1000")], h)).get("data") or []
            cat = next((s["category"] for s in live if game_key((s.get("category") or {}).get("name", "")) in want), None)
            if cat and cat.get("id"):
                return int(cat["id"])
        except KickError as e:
            errors.append(str(e))
        self._warn_once("kick-cat", f"Kick has no category named {d.game!r} yet, or Kick's API didn't answer"
                        f"{' (' + errors[-1] + ')' if errors else ''}. Set [kick] category_id in config.toml to override")
        return None

    async def _kick(self) -> list[Stream]:
        h = await self._kick_headers()
        if not h:
            return []
        langs = self.cfg.discovery.languages
        if not self._kick_category_id:
            self._kick_category_id = await self._kick_category(h)
            if not self._kick_category_id:
                return []
            log.info("Kick: %s is category %s", self.cfg.discovery.game, self._kick_category_id)
        try:
            data = (await self._kick_get("/v2/livestreams", [("category_id", str(self._kick_category_id)),
                                                             ("limit", "1000")], h)).get("data") or []
        except KickError as e:
            if e.status not in (400, 404, 410):
                raise
            data = (await self._kick_get("/v1/livestreams", {"category_id": self._kick_category_id,
                                                             "sort": "viewer_count", "limit": 100}, h)).get("data") or []
        want = self._kick_wanted()
        if not data:
            # Nothing in that category: maybe the id is wrong. Look through Kick's biggest live streams instead
            # and keep the ones playing the game (and remember its real category id).
            live = (await self._kick_get("/v2/livestreams", [("limit", "1000")], h)).get("data") or []
            data = [s for s in live if game_key((s.get("category") or {}).get("name", "")) in want]
            if data and data[0]["category"].get("id") and not self.cfg.creds.kick_category_id:
                self._kick_category_id = int(data[0]["category"]["id"])
            log.info("Kick: nothing came back for category %s; found %d %s streams among Kick's biggest",
                     self._kick_category_id, len(data), self.cfg.discovery.game)
        out = []
        for s in data:
            cat = (s.get("category") or {}).get("name")
            if cat and game_key(cat) not in want:
                continue
            lang = s.get("language") or s.get("language_code")
            title = s.get("stream_title") or s.get("title") or ""
            if matches_language(lang, langs) is False:
                continue
            if matches_language(lang, langs) is None and "en" in langs and looks_non_english(title):
                continue
            user = s.get("broadcaster_user") or {}
            slug = s.get("slug") or (s.get("channel") or {}).get("slug") or user.get("username")
            if slug:
                out.append(Stream("kick", slug.lower(), f"https://kick.com/{slug}",
                                  int(s.get("viewer_count") or 0), title, user.get("username") or slug))
        return sorted(out, key=lambda st: st.viewers, reverse=True)


async def platform_report(cfg: Config) -> list[tuple[str, int | None, str]]:
    """For the Check tab: how many live streams of the game each platform finds right now.
    YouTube is left out: each search uses a good part of its small daily quota."""
    out = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
        disc = Discovery(cfg, s)
        for name, fn, have in (("Twitch", disc._twitch, cfg.creds.twitch_client_id),
                               ("Kick", disc._kick, cfg.creds.kick_client_id)):
            if not have:
                continue
            try:
                got = await fn()
                top = max(got, key=lambda st: st.viewers) if got else None
                out.append((name, len(got), f"biggest: {top.display_name or top.channel}, {top.viewers:,} viewers" if top else ""))
            except Exception as e:  # noqa: BLE001
                out.append((name, None, str(e)[:200]))
    return out
