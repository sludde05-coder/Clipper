"""The phone app, driven in a phone-sized browser against a real Clipper app (feed, posting, editing,
deleting, clipping controls, settings, Top 10), plus checks that it stays light."""
import asyncio
import glob
import json
import shutil
import threading
import tomllib

import pytest
from aiohttp import web

from clipper import naming
from clipper.app import ClipperApp
from clipper.phone import PhoneServer

from test_app import make_library

CHROME = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
pytestmark = pytest.mark.skipif(not CHROME, reason="no browser available for this test")


@pytest.fixture()
def server(tmp_path):
    conf, phone, det, src = make_library(tmp_path)
    # 6 clips of 3 streamers, each with its own original so it can be re-rendered
    root = phone.parent.parent.parent
    for i, s in enumerate(["xQc", "Lacy", "xQc", "Lacy", "Jynxzi"], 2):
        stem = f"{s}_2026-11-19_21-0{i}-00_{i}"
        for folder, ext, srcf in ((naming.PHONE, ".mp4", phone), (naming.SOURCE, ".mp4", src), (naming.DETAILS, ".json", det)):
            dst = root / s / folder / (stem + ext)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(srcf, dst)
        meta = json.loads((root / s / naming.DETAILS / (stem + ".json")).read_text())
        meta.update(name=s, chat_rate=10 + i, normal_rate=1)
        (root / s / naming.DETAILS / (stem + ".json")).write_text(json.dumps(meta))
    text = conf.read_text(encoding="utf-8").replace("[phone]\nenabled = false", '[phone]\nenabled = false\nkey = "k1"')
    conf.write_text(text + '[anthropic]\napi_key = "sk-secret-do-not-show"\n', encoding="utf-8")

    ready, box = threading.Event(), {}

    def serve():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def start():
            app = ClipperApp(str(conf))
            app.cfg.phone.key = "k1"
            app.cfg.vertical.ai_captions = False
            ph = PhoneServer(app.cfg, None, library=app)
            runner = web.AppRunner(ph.app(), access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            box.update(app=app, port=site._server.sockets[0].getsockname()[1], loop=loop, runner=runner)
            ready.set()
        loop.run_until_complete(start())
        loop.run_forever()
    threading.Thread(target=serve, daemon=True).start()
    ready.wait(20)
    yield box, conf, root
    box["loop"].call_soon_threadsafe(box["loop"].stop)


def browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(executable_path=CHROME[-1], args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    return pw, b, ctx.new_page()


def test_phone_app_every_flow(server):
    box, conf, root = server
    app, url = box["app"], f"http://127.0.0.1:{box['port']}/?k=k1"
    pw, b, p = browser()
    errors, requests = [], []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.on("request", lambda r: requests.append(r.url))
    p.on("dialog", lambda d: d.accept())
    try:
        # ---- feed: light (only nearby pictures and videos), small previews, one set of buttons
        p.goto(url)
        p.wait_for_selector("#feed .item")
        p.wait_for_timeout(1500)
        assert p.locator("#feed .item").count() == 6
        assert p.locator("#feed video").count() <= 2 and p.locator(".side").count() == 1
        assert sum("/thumb" in u for u in requests) <= 6
        assert all("/preview" in u for u in requests if "/media" in u or "/preview" in u)
        assert p.locator("#ohook").inner_text()

        # ---- post: captions per platform, mark posted (saved on the PC)
        first = p.locator("#feed .item").first.get_attribute("data-id")
        p.click('#side [data-a="post"]')
        p.wait_for_selector('#sheetbody .platform[data-p="tiktok"]')
        assert p.locator('#sheetbody textarea[data-f="caption"]').first.input_value()
        p.click('#sheetbody .platform[data-p="tiktok"] [data-act="mark"]')
        p.wait_for_timeout(500)
        clip = app._clip(first)
        assert app._meta(clip)["posted"]["tiktok"]
        p.go_back()
        assert p.locator("#sheet").is_hidden()

        # ---- edit: new headline -> re-rendered on the PC
        p.click('#side [data-a="edit"]')
        p.wait_for_selector("#e-hook")
        assert p.locator("#e-layout option").count() >= 2
        p.fill("#e-hook", "Kai went on a date in GTA 6 😭")
        p.click("#e-save")
        p.wait_for_function("() => document.getElementById('sheet').hidden", timeout=120000)
        assert app._meta(clip)["captions"]["hook"] == "Kai went on a date in GTA 6 😭"

        # ---- pick 2 for a Top 10, then delete one clip (to Deleted clips)
        p.click('#side [data-a="pick"]')
        p.locator("#feed").evaluate("f => f.scrollBy(0, f.clientHeight)")
        p.wait_for_timeout(700)
        second = p.evaluate("() => document.querySelectorAll('#feed .item')[1].dataset.id")
        p.click('#side [data-a="pick"]')
        assert p.locator("#pickbar").is_visible() and "Top 2" in p.locator("#pickmake").inner_text()
        p.locator("#feed").evaluate("f => f.scrollBy(0, f.clientHeight)")
        p.wait_for_timeout(700)
        gone = p.evaluate("() => document.querySelectorAll('#feed .item')[2].dataset.id")
        p.click('#side [data-a="del"]')
        p.wait_for_timeout(700)
        assert not (root / gone).exists() and (root / "Deleted clips").exists()
        assert p.locator("#feed .item").count() == 5

        # ---- clipping tab: top N + links saved, start and stop
        p.click('#nav [data-v="clipping"]')
        p.wait_for_selector("#startstop")
        assert "Not clipping" in p.locator("#cmode").inner_text()
        p.fill("#topn", "3")
        p.fill("#pins", "https://kick.com/adinross")
        p.click("#savetargets")
        p.wait_for_timeout(500)
        saved = tomllib.loads(conf.read_text(encoding="utf-8"))["discovery"]
        assert saved["top_n"] == 3 and saved["always_track"] == ["https://kick.com/adinross"]
        p.click("#startstop")
        p.wait_for_function("() => document.getElementById('cmode').textContent.startsWith('Clipping')", timeout=10000)
        assert p.locator("#log div").count() > 0
        p.click("#startstop")
        p.wait_for_function("() => document.getElementById('cmode').textContent === 'Not clipping'", timeout=15000)

        # ---- settings: no keys shown; a change is saved
        p.click('#nav [data-v="settings"]')
        p.wait_for_selector("#sfields .card")
        assert "sk-secret" not in p.content() and "API key" not in p.locator("#sfields").inner_text()
        box_ = p.locator("#sfields label.switch", has_text="Whoosh between Top 10 moments").locator("input")
        box_.uncheck()
        p.click("#ssave")
        p.wait_for_timeout(600)
        assert tomllib.loads(conf.read_text(encoding="utf-8"))["vertical"]["top_sfx"] is False

        # ---- Top 10 from the 2 picks: one player, a custom part, made on the PC
        p.click('#nav [data-v="clips"]')
        p.click("#pickmake")
        p.wait_for_selector("#tlist .moment")
        assert p.locator("#tlist .moment").count() == 2 and p.locator("#p-top video").count() == 1
        p.locator("#tlist .moment").nth(1).click()
        p.locator("#tlist .moment").nth(1).locator('input[data-k="start"]').fill("1")
        p.locator("#tlist .moment").nth(1).locator('input[data-k="start"]').dispatch_event("change")
        p.locator("#tmusic").uncheck()
        p.click("#tmake")
        p.wait_for_function("() => !document.getElementById('makingcard').hidden", timeout=5000)
        p.wait_for_function("() => document.getElementById('makingcard').hidden", timeout=180000)
        made = list((root / "Top moments" / naming.PHONE).glob("*.mp4"))
        assert len(made) == 1
        meta = json.loads((root / "Top moments" / naming.DETAILS / (made[0].stem + ".json")).read_text(encoding="utf-8"))
        assert {x["clip"] for x in meta["compilation"]} == {app._clip(first).name, app._clip(second).name}
        assert any(x["start"] == 1.0 for x in meta["compilation"])
        assert p.locator("#who").input_value() == "Top moments"
        assert errors == []
    finally:
        b.close()
        pw.stop()


def test_feed_stays_light_with_many_clips(server):
    box, conf, root = server
    phone = next(root.glob(f"*/{naming.PHONE}/*.mp4"))
    det = phone.parent.parent / naming.DETAILS / (phone.stem + ".json")
    for i in range(80):
        dst = root / "Many" / naming.PHONE / f"Many_2026-11-18_10-00-{i:02d}_{i + 1}.mp4"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(phone, dst)
        d = root / "Many" / naming.DETAILS / (dst.stem + ".json")
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(det, d)
    pw, b, p = browser()
    thumbs = []
    p.on("request", lambda r: thumbs.append(r.url) if "/thumb" in r.url else None)
    try:
        p.goto(f"http://127.0.0.1:{box['port']}/?k=k1")
        p.wait_for_selector("#feed .item")
        p.wait_for_timeout(1500)
        assert p.locator("#feed .item").count() == 86
        assert len(thumbs) <= 6                                       # not 86
        assert p.evaluate("() => document.getElementsByTagName('*').length") < 600
        for _ in range(5):
            p.locator("#feed").evaluate("f => f.scrollBy(0, f.clientHeight)")
            p.wait_for_timeout(300)
        assert p.locator("#feed video").count() <= 3                  # only around the one on screen
    finally:
        b.close()
        pw.stop()
