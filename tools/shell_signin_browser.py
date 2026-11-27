"""Real-Chromium check: the offline shell must not spin for ever when the gateway asks for sign-in.

    python tools/shell_signin_browser.py . [--case slow]

The same file runs in the basketball and baseball repos (2026-11-27 phone report).
The fake site (localhost) runs the repo's web/sw.js and web/static/offline/shell.js with a
stub engine. Its /app answers like the Pocket ID gateway with an expired session: a 302 to a
second origin (127.0.0.1) whose login page sends frame-ancestors 'none'.
  slow:    the first /app takes 6 s (past LOCAL_TIMEOUT), so the worker serves the shell,
           then the shell's frame asks again and gets the redirect (server log 2026-11-27 16:49).
Pass: the window ends on the login page at the top level. Fail: still the shell's spinner.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(sys.argv[1])
SW = (REPO / "web" / "sw.js").read_text()
SHELL = (REPO / "web" / "static" / "offline" / "shell.js").read_text()
ENGINE = 'self.postMessage({type: "progress", text: "Starting the site"});\n'
LOG: list[str] = []
STATE = {"app_hits": 0}


def config(site_port: int) -> str:
    return "const CONFIG = " + json.dumps({
        "static": [], "pages": ["/app"], "imageHosts": [], "imagePaths": [], "dataPaths": [],
        "site": "Test", "css": "/x.css",
        "offline": {"shell": "/static/offline/shell.js?v=1", "engine": "/static/offline/engine.js?v=1"},
    }) + ";\n"


SETUP = """<!doctype html><title>setup</title><body>setup<script>
(async () => {
  await navigator.serviceWorker.register('/sw.js');
  await navigator.serviceWorker.ready;
  const meta = await caches.open('meta-v1');
  await meta.put('/__offline/manifest', new Response(JSON.stringify({version: 'v1', built_at: '2026-11-27T10:00:00Z'}),
    {headers: {'x-checked': '2026-11-27T10:00:00Z'}}));
  document.title = 'ready';
})();
</script>"""


def site_handler(gateway: str):
    class Site(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body=b"", ctype="text/html; charset=utf-8", headers=()):
            self.send_response(status)
            self.send_header("content-type", ctype)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path
            LOG.append(f"{time.monotonic():.1f} site {path} dest={self.headers.get('Sec-Fetch-Dest')} "
                       f"preload={self.headers.get('Service-Worker-Navigation-Preload')}")
            if path.startswith("/setup"):
                return self.send(200, SETUP.encode())
            if path.startswith("/sw.js"):
                return self.send(200, (config(self.server.server_port) + SW).encode(), "text/javascript")
            if path.startswith("/static/offline/shell.js"):
                return self.send(200, SHELL.encode(), "text/javascript")
            if path.startswith("/static/offline/engine.js"):
                return self.send(200, ENGINE.encode(), "text/javascript")
            if path.startswith("/app"):
                STATE["app_hits"] += 1
                if STATE["app_hits"] == 1 and STATE.get("case") == "slow":
                    time.sleep(6)
                return self.send(302, b"", headers=[("location", f"{gateway}/login?rd=/app")])
            return self.send(404, b"no")
    return Site


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        LOG.append(f"{time.monotonic():.1f} gateway {self.path} dest={self.headers.get('Sec-Fetch-Dest')}")
        body = b"<!doctype html><title>LOGIN</title><h1>Pocket ID login</h1>"
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.send_header("content-security-policy", "frame-ancestors 'none'")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    STATE["case"] = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--case" else "slow"
    gw = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    gateway = f"http://127.0.0.1:{gw.server_port}"
    site = ThreadingHTTPServer(("localhost", 0), site_handler(gateway))
    base = f"http://localhost:{site.server_port}"
    for server in (gw, site):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 412, "height": 900})
        page = context.new_page()
        page.goto(base + "/setup")
        page.wait_for_function("document.title === 'ready'", timeout=15000)
        page.reload()                     # now controlled by the worker
        page.wait_for_timeout(500)
        STATE["app_hits"] = 0
        try:
            page.goto(base + "/app", wait_until="commit", timeout=20000)
        except Exception as error:        # a navigation that ends cross-origin may abort the wait
            LOG.append(f"goto: {error}")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and "/login" not in page.url:
            page.wait_for_timeout(500)
        url = page.url
        boot = None
        if url.startswith(base):
            boot = page.evaluate("() => { const b = document.getElementById('boot'); "
                                 "return b ? {hidden: b.hidden, text: b.innerText} : null; }")
        browser.close()
    print("\n".join(LOG))
    print("final url:", url)
    print("boot:", boot)
    ok = url.startswith(gateway + "/login")
    print("PASS: sign-in opened at the top level" if ok else "FAIL: window stuck in the offline shell")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
