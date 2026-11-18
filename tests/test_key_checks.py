"""How key checks read the site's answer."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from clipper import setup_wizard as w


def check(status, body, ctype):
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["ua"] = self.headers.get("User-Agent", "")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/oauth/token"
        return w._check(lambda: w._post(url, {"grant_type": "client_credentials"})), seen
    finally:
        srv.shutdown()


def test_works_and_names_itself():
    (ok, _), seen = check(200, '{"access_token": "t"}', "application/json")
    assert ok is True and seen["ua"].startswith("Clipper/")


def test_protection_page_is_not_called_a_wrong_key():
    (ok, msg), _ = check(403, "<html><body>Access denied</body></html>", "text/html")
    assert ok is None and "doesn't mean the key is wrong" in msg


def test_real_rejection_is_still_reported():
    (ok, msg), _ = check(401, '{"error": "invalid_client"}', "application/json")
    assert ok is False and "rejected (401)" in msg
