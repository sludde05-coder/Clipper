"""The phone app: a small web server on the PC that lets a phone post the clips in the POST folder.

When it runs inside the Clipper app (the normal case), the phone gets the whole clip library like
the PC app: every clip with its captions, posting (share/save + caption copied), deleting, and
the Top 10 editor. Those calls go straight to the PC app's own handlers (see LIBRARY below).

The phone opens it once by scanning a QR code (menu option 8), then adds it to the home
screen, where it works like an app. Everything goes over the home Wi-Fi; the secret key in
the QR code keeps other people on the network out.

  GET  /                     the app (HTML/JS)
  GET  /api/clips            clips waiting in POST, with captions per platform
  GET  /media/<name>         the video (supports seeking; ?download=1 to save it)
  GET  /thumb/<name>         a preview image
  POST /api/clips/<name>/done   move the clip to POST/posted, logging what was posted
  GET  /connect              the QR code page (only opened on the PC itself)
"""
from __future__ import annotations

import asyncio
import hmac
import io
import json
import logging
import secrets
import socket
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from .config import Config
from .proc import NO_WINDOW
from .poster import TARGETS, VIDEO_EXT, captions_for, find_metadata, move_to_posted

log = logging.getLogger(__name__)
APP_DIR = Path(__file__).parent / "phone_app"
PLATFORM_LABEL = {"twitch": "Twitch", "youtube": "YouTube", "kick": "Kick"}
# The PC app's handlers the phone may use: (method, phone path, ClipperApp method). Only these.
LIBRARY = [
    ("GET", "/lib/clips", "clips"), ("GET", "/lib/clip", "clip_detail"),
    ("POST", "/lib/clip/delete", "delete_clip"), ("POST", "/lib/clip/posted", "mark_posted"),
    ("POST", "/lib/clip/finish", "finish_clip"), ("POST", "/lib/clip/post-captions", "save_post"),
    ("GET", "/lib/compilation/plan", "compilation_plan"), ("POST", "/lib/compilation", "compilation"),
    ("GET", "/lib/job", "job"),
    ("GET", "/media", "media"), ("GET", "/thumb", "thumb"), ("GET", "/api/cover", "cover"),
]


def lan_ip() -> str:
    """This PC's address on the home network (what the phone connects to)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packet is sent; this just picks the right network card
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


_ts_cache: tuple[float, str | None] = (0.0, None)


def _tailscale_cli() -> str | None:
    import shutil
    import sys
    found = shutil.which("tailscale")
    if found:
        return found
    for p in ([r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe"]
              if sys.platform == "win32" else
              ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/usr/local/bin/tailscale", "/usr/bin/tailscale"]):
        if Path(p).exists():
            return p
    return None


def tailscale_ip() -> str | None:
    """This PC's Tailscale address (100.x.y.z) when Tailscale is installed, signed in and running.
    A phone with Tailscale on reaches it from anywhere: mobile data, any Wi-Fi. Checked at most once a minute."""
    import subprocess
    import time
    global _ts_cache
    if time.time() - _ts_cache[0] < 60:
        return _ts_cache[1]
    ip = None
    cli = _tailscale_cli()
    if cli:
        try:
            r = subprocess.run([cli, "status", "--json"], capture_output=True, text=True, timeout=4, **NO_WINDOW)
            st = json.loads(r.stdout or "{}")
            if st.get("BackendState") == "Running":
                ip = next((a for a in (st.get("Self") or {}).get("TailscaleIPs") or [] if "." in a), None)
        except (OSError, ValueError, subprocess.SubprocessError):
            ip = None
    _ts_cache = (time.time(), ip)
    return ip


def ensure_key(cfg: Config, config_path: str | None) -> str:
    """Create the secret key once and save it in config.toml, so the phone keeps working."""
    if cfg.phone.key:
        return cfg.phone.key
    cfg.phone.key = secrets.token_urlsafe(18)
    if config_path and Path(config_path).exists():
        from .setup_wizard import set_value
        p = Path(config_path)
        p.write_text(set_value(p.read_text(encoding="utf-8"), "phone", "key", cfg.phone.key), encoding="utf-8")
    return cfg.phone.key


class PhoneServer:
    def __init__(self, cfg: Config, config_path: str | None = "config.toml", library=None):
        self.cfg = cfg
        self.library = library        # the ClipperApp, when the phone app runs inside it
        self.key = ensure_key(cfg, config_path)
        self.folder = Path(cfg.post.folder)
        self.clips_dir = Path(cfg.clips.output_dir)
        self.thumbs = self.folder / ".thumbs"
        self.runner: web.AppRunner | None = None

    # ------------------------------------------------------------ addresses

    def addresses(self) -> dict[str, str | None]:
        """Where the phone can reach this PC: the home network, and Tailscale (from anywhere) if it runs."""
        ts = tailscale_ip() if self.cfg.phone.use_tailscale else None
        return {"wifi": f"http://{lan_ip()}:{self.cfg.phone.port}",
                "anywhere": self.cfg.phone.public_url.rstrip("/") or (f"http://{ts}:{self.cfg.phone.port}" if ts else None)}

    @property
    def base_url(self) -> str:
        a = self.addresses()
        return a["anywhere"] or a["wifi"]

    def url_for(self, where: str) -> str:
        """The phone link (with its key) for "wifi" or "anywhere"."""
        a = self.addresses()
        return f"{(a.get(where) or a['anywhere'] or a['wifi'])}/?k={self.key}"

    @property
    def phone_url(self) -> str:
        return f"{self.base_url}/?k={self.key}"

    # ------------------------------------------------------------ helpers

    def _authorized(self, request: web.Request) -> bool:
        given = request.headers.get("X-Clipper-Key") or request.query.get("k") or ""
        return hmac.compare_digest(given, self.key)

    def _clip(self, name: str) -> Path:
        """A clip in POST by name; refuses anything that tries to leave the folder."""
        p = (self.folder / name).resolve()
        if p.parent != self.folder.resolve() or p.suffix.lower() not in VIDEO_EXT or not p.is_file():
            raise web.HTTPNotFound()
        return p

    def _clips(self) -> list[Path]:
        if not self.folder.exists():
            return []
        vids = [p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT]
        return sorted(vids, key=lambda p: p.stat().st_mtime, reverse=True)

    def _describe(self, clip: Path) -> dict:
        meta = find_metadata(clip, self.clips_dir)
        caps = captions_for(meta, clip, self.cfg.post)
        name = quote(clip.name)
        return {
            "name": clip.name,
            "video": f"/media/{name}?k={self.key}",
            "download": f"/media/{name}?k={self.key}&download=1",
            "thumb": f"/thumb/{name}?k={self.key}",
            "streamer": meta.get("name") or "",
            "source": PLATFORM_LABEL.get(meta.get("platform", ""), ""),
            "hook": (meta.get("captions") or {}).get("hook", ""),
            "size_mb": round(clip.stat().st_size / 1e6, 1),
            "added": clip.stat().st_mtime,
            "platforms": [{"key": k, "name": TARGETS[k].name, **caps[k]}
                          for k in self.cfg.post.platforms if k in TARGETS],
        }

    # ------------------------------------------------------------ routes

    @web.middleware
    async def guard(self, request: web.Request, handler):
        public = request.path in ("/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png",
                                  "/apple-touch-icon.png", "/connect", "/qr.svg")
        if not public and not self._authorized(request):
            return web.json_response({"error": "wrong or missing key: scan the QR code again"}, status=403)
        return await handler(request)

    async def index(self, request: web.Request) -> web.Response:
        # Inside the Clipper app: the whole library. On its own (menu option 8): just the POST folder.
        html = (APP_DIR / ("library.html" if self.library is not None else "index.html")).read_text(encoding="utf-8")
        k = request.query.get("k", "")
        # The manifest carries the key too, so the home-screen app opens already connected.
        manifest = f"/manifest.webmanifest?k={quote(k)}" if hmac.compare_digest(k, self.key) else "/manifest.webmanifest"
        return web.Response(text=html.replace("{{MANIFEST}}", manifest), content_type="text/html",
                            headers={"Cache-Control": "no-store"})

    async def manifest(self, request: web.Request) -> web.Response:
        k = request.query.get("k", "")
        start = f"/?k={quote(k)}" if hmac.compare_digest(k, self.key) else "/"
        return web.json_response({
            "name": "Clipper", "short_name": "Clipper", "start_url": start, "scope": "/",
            "display": "standalone", "background_color": "#0f1115", "theme_color": "#0f1115",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}],
        }, content_type="application/manifest+json")

    async def static(self, request: web.Request) -> web.StreamResponse:
        name = {"/icon-192.png": "icon-192.png", "/icon-512.png": "icon-512.png",
                "/apple-touch-icon.png": "icon-192.png"}[request.path]
        return web.FileResponse(APP_DIR / name)

    async def list_clips(self, request: web.Request) -> web.Response:
        return web.json_response({"clips": [self._describe(c) for c in self._clips()]},
                                 headers={"Cache-Control": "no-store"})

    async def media(self, request: web.Request) -> web.StreamResponse:
        clip = self._clip(request.match_info["name"])
        headers = {"Cache-Control": "no-store"}
        if request.query.get("download"):
            headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(clip.name)}"
        return web.FileResponse(clip, headers=headers)  # handles Range, which phones need to play video

    async def thumb(self, request: web.Request) -> web.StreamResponse:
        clip = self._clip(request.match_info["name"])
        self.thumbs.mkdir(parents=True, exist_ok=True)
        out = self.thumbs / (clip.stem + ".jpg")
        if not out.exists() or out.stat().st_mtime < clip.stat().st_mtime:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1", "-i", str(clip),
                "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5", str(out),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **NO_WINDOW)
            await proc.wait()
        if not out.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(out)

    async def done(self, request: web.Request) -> web.Response:
        clip = self._clip(request.match_info["name"])
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        results = {k: ("posted" if body.get(k) == "posted" else "skipped")
                   for k in self.cfg.post.platforms if k in TARGETS}
        move_to_posted(self.folder, clip, results)
        (self.thumbs / (clip.stem + ".jpg")).unlink(missing_ok=True)
        posted = [TARGETS[k].name for k, v in results.items() if v == "posted"]
        log.info("📱 %s posted from the phone (%s), moved to posted/", clip.name, ", ".join(posted) or "nowhere")
        return web.json_response({"ok": True})

    async def info(self, request: web.Request) -> web.Response:
        lib = self.library
        return web.json_response({"library": lib is not None,
                                  "platforms": [{"key": k, "name": TARGETS[k].name} for k in
                                                (lib._platforms() if lib else self.cfg.post.platforms) if k in TARGETS]})

    def _forward(self, name: str):
        """A phone route that runs the PC app's handler of the same job (key checked by guard)."""
        async def handler(request: web.Request) -> web.StreamResponse:
            if self.library is None:
                raise web.HTTPNotFound(text="open the Clipper app on your PC")
            resp = await getattr(self.library, name)(request)
            if request.query.get("download") and isinstance(resp, web.FileResponse):
                fname = request.query.get("name") or "clip.mp4"
                resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(fname)}"
            return resp
        return handler

    async def connect(self, request: web.Request) -> web.Response:
        # Shows the secret, so only on the PC itself.
        if request.remote not in ("127.0.0.1", "::1"):
            raise web.HTTPForbidden(text="Open this page on the PC that runs the clipper.")
        html = (APP_DIR / "connect.html").read_text(encoding="utf-8")
        return web.Response(text=html.replace("{{URL}}", self.phone_url).replace("{{BASE}}", self.base_url),
                            content_type="text/html", headers={"Cache-Control": "no-store"})

    async def qr(self, request: web.Request) -> web.Response:
        if request.remote not in ("127.0.0.1", "::1"):
            raise web.HTTPForbidden()
        return web.Response(body=qr_svg(self.phone_url), content_type="image/svg+xml")

    # ------------------------------------------------------------ lifecycle

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.guard], client_max_size=1024 ** 2)
        app.router.add_get("/", self.index)
        app.router.add_get("/manifest.webmanifest", self.manifest)
        for p in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"):
            app.router.add_get(p, self.static)
        app.router.add_get("/api/clips", self.list_clips)
        app.router.add_get("/media/{name}", self.media)
        app.router.add_get("/thumb/{name}", self.thumb)
        app.router.add_post("/api/clips/{name}/done", self.done)
        app.router.add_get("/connect", self.connect)
        app.router.add_get("/qr.svg", self.qr)
        app.router.add_get("/api/info", self.info)
        for method, path, name in LIBRARY:
            app.router.add_route(method, path, self._forward(name))
        return app

    async def start(self) -> bool:
        """Start serving; False if the port is taken (e.g. the clipper already runs in another window)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.runner = web.AppRunner(self.app(), access_log=None)
        await self.runner.setup()
        try:
            await web.TCPSite(self.runner, "0.0.0.0", self.cfg.phone.port).start()
        except OSError:
            await self.runner.cleanup()
            self.runner = None
            return False
        log.info("📱 Phone app ready at %s  (menu option 8 shows the QR code)", self.base_url)
        return True

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()


def qr_svg(text: str) -> bytes:
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathFillImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


async def serve_forever(cfg: Config, config_path: str | None) -> None:
    """`python -m clipper phone`: run the phone app and show the QR code on the PC."""
    import webbrowser
    server = PhoneServer(cfg, config_path)
    started = await server.start()
    if not started:
        print(f"The phone app is already running (port {cfg.phone.port} is in use), probably in another clipper "
              "window. Showing its QR code.")
    print(f"\nOpening the QR code on this PC: http://localhost:{cfg.phone.port}/connect")
    print("Scan it with your phone's camera. Your phone must be on the same Wi-Fi as this PC.")
    webbrowser.open(f"http://localhost:{cfg.phone.port}/connect")
    if not started:
        return
    print("Keep this window open while you post. Press Ctrl+C to stop.\n")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await server.stop()
