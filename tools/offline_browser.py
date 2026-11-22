"""Browser check of the full offline copy against a running site.

    python offline_browser.py http://127.0.0.1:8061 [--key KEY] [--browser chromium|firefox|webkit]
                              [--site baseball|basketball] [--shots DIR]

Downloads the copy through the About card, cuts the connection, and uses the site:
cold open, links, search, filters, charts, images, back, reload, then back online.
Each page's main text is compared with the same page as the server renders it.
Prints one line per check and exits 1 if any failed.
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

SITES = {
    "baseball": {
        "pages": ["/standings", "/players", "/player/15640", "/team/NYY", "/players?kind=pit&mode=advanced",
                  "/teams?season=1998", "/player/1002378", "/team/BOS?season=1975", "/about"],
        "search": ("judge", "Aaron Judge"),
        "nav": ("Players", "/players"),
        "chart": "/chart",
        "image_page": "/team/NYY",
        "image": "img[src^='/logos/']",
        "filter": ("/players", "select[data-nav='season']", "1998", "season=1998"),
        "photo": "/player/15640",
    },
    "basketball": {
        "pages": ["/standings", "/players", "/player/3934672", "/team/NYK", "/teams", "/team/NYK/games", "/trade",
                  "/players?season=2016&mode=advanced", "/team/CHI?season=1996", "/player/1035", "/about"],
        "search": ("brunson", "Jalen Brunson"),
        "nav": ("Players", "/players"),
        "chart": "/chart",
        "image_page": "/team/NYK",
        "image": "img[src^='/static/logos/'], img[src^='/img/player/']",
        "filter": ("/players", "select[data-nav='team']", "NYK", "team=NYK"),
        "photo": "/player/3934672",
    },
}
checks: list[tuple[bool, str]] = []


class Link:
    """A relay in front of the site that can be cut.

    Browsers' offline emulation is uneven (Firefox does not apply it to a service
    worker's requests), so the connection is also cut for real: while down, every
    open connection is reset and new ones are reset on arrival.
    """

    def __init__(self, base):
        target = urlsplit(base)
        self.target = (target.hostname, target.port or 80)
        self.up = True
        self.open: set[socket.socket] = set()
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(256)
        self.base = f"http://127.0.0.1:{self.server.getsockname()[1]}"
        threading.Thread(target=self._accept, daemon=True).start()

    @staticmethod
    def _reset(sock):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            sock.close()
        except OSError:
            pass

    def _accept(self):
        while True:
            client, _ = self.server.accept()
            if not self.up:
                self._reset(client)
                continue
            try:
                upstream = socket.create_connection(self.target, timeout=10)
                upstream.settimeout(None)
            except OSError:
                self._reset(client)
                continue
            self.open |= {client, upstream}
            for source, sink in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pump, args=(source, sink), daemon=True).start()

    def _pump(self, source, sink):
        try:
            while data := source.recv(65536):
                sink.sendall(data)
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        finally:
            if not self.up:
                self._reset(source), self._reset(sink)
            self.open.discard(source)

    def cut(self, down):
        self.up = not down
        if down:
            for sock in list(self.open):
                self._reset(sock)
            self.open.clear()


def check(ok, text):
    checks.append((bool(ok), text))
    print(("ok   " if ok else "FAIL ") + text, flush=True)


def main_text(target):
    """The page's main content as text, without the offline banner and the offline card."""
    return target.evaluate("""() => {
        const main = document.querySelector('main.page').cloneNode(true);
        main.querySelectorAll('.offline-note, #offline-card').forEach(node => node.remove());
        return main.innerText.replace(/\\s+/g, ' ').trim();
    }""")


def run(args):
    site = SITES[args.site]
    link = Link(args.base)
    args.base = link.base

    with sync_playwright() as p, tempfile.TemporaryDirectory() as profile:
        # A profile on disk, as on a real device: WebKit gives a throwaway one no file storage.
        mobile = {} if args.browser == "firefox" else {"is_mobile": True, "has_touch": True}
        context = getattr(p, args.browser).launch_persistent_context(
            profile, viewport={"width": 412, "height": 915}, device_scale_factor=2, **mobile)
        page = context.pages[0] if context.pages else context.new_page()
        problems = []

        def offline(down):
            # Firefox's emulation only covers the page: its service worker stays online and
            # the page's own requests are answered from the HTTP cache, a state no device is
            # ever in. There the relay alone is cut (connected, but the site unreachable).
            if args.browser != "firefox":
                context.set_offline(down)
            link.cut(down)
        page.on("pageerror", lambda error: problems.append(f"[after check {len(checks)}] pageerror: {error}"))
        page.on("console", lambda m: problems.append(f"[after check {len(checks)}] console {m.type}: {m.text}") if m.type == "error" else None)

        # -- online: what the server renders (in a separate profile, so nothing is saved
        #    in the one under test), then the download
        expect = {}
        plain = getattr(p, args.browser).launch()
        reference = plain.new_context(viewport={"width": 412, "height": 915}, service_workers="block").new_page()
        for path in site["pages"]:
            reference.goto(args.base + path)
            expect[path] = main_text(reference)
        plain.close()
        if args.key:                        # a public site: nothing is shown to a visitor without the key
            page.goto(args.base + "/about")
            page.wait_for_load_state("networkidle")
            check(page.locator("#offline-card").is_hidden(), "without the key About shows no offline card")
        page.goto(args.base + "/about" + (f"?offline_key={args.key}" if args.key else ""))
        page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=30000)
        card = page.locator("#offline-card")
        card.get_by_role("button", name="Download").wait_for(timeout=180000)
        print("card:", card.locator("p").first.inner_text(), flush=True)
        if args.shots:
            page.screenshot(path=f"{args.shots}/{args.site}-{args.browser}-card.png")
        began = time.time()
        card.get_by_role("button", name="Download").click()
        page.wait_for_function(
            "document.querySelector('#offline-card p').textContent.startsWith('On this device')", timeout=900000)
        took = time.time() - began
        # The photos follow the copy; the card shows a bar while they arrive.
        page.wait_for_function("document.querySelector('#offline-card progress').hidden", timeout=900000)
        photos = page.evaluate("caches.open('photos-v1').then(c => c.keys()).then(k => k.length)")
        print(f"photos after {time.time() - began:.0f} s: {photos}", flush=True)
        estimate = page.evaluate("navigator.storage.estimate()")
        manifest = page.evaluate("caches.open('meta-v1').then(c => c.match('/__offline/manifest')).then(r => r.json())")
        print(f"downloaded in {took:.0f} s; card: {card.locator('p').first.inner_text()}", flush=True)
        print(f"storage in use {estimate.get('usage', 0) / 1e6:.0f} MB of {estimate.get('quota', 0) / 1e9:.1f} GB quota; "
              f"manifest says {manifest['bytes'] / 1e6:.0f} MB on the device, {manifest['download'] / 1e6:.0f} MB to download")
        check(estimate.get("usage", 0) > manifest["bytes"] * 0.9, "the device holds the whole copy")
        listed = (manifest.get("photos") or {}).get("count", 0)
        check(listed and photos >= listed * 0.98, f"and this season's player photos ({photos} of {listed})")
        if args.shots:
            page.screenshot(path=f"{args.shots}/{args.site}-{args.browser}-ready.png")
        # The worker saves the main pages in the background on the first visit. Let that
        # finish, then confirm the copy is current: pages saved before that moment give
        # way to the copy, which is what the checks below exercise.
        count = -1
        while True:
            now = page.evaluate("caches.open('pages-v1').then(c => c.keys()).then(k => k.length)")
            if now == count:
                break
            count = now
            time.sleep(4)
        checked = "caches.open('meta-v1').then(c => c.match('/__offline/manifest')).then(r => r.headers.get('x-checked'))"
        before = page.evaluate(checked)
        time.sleep(1.1)                     # saved pages are stamped to the second
        card.get_by_role("button", name="Check for an update").click()
        deadline = time.time() + 60
        while page.evaluate(checked) == before:
            assert time.time() < deadline, "the copy was not confirmed current"
            time.sleep(0.5)

        # -- no connection: a cold open of the home page
        page.wait_for_load_state("networkidle")
        offline(True)
        fresh = context.new_page()
        fresh.on("pageerror", lambda error: problems.append(f"[after check {len(checks)}] pageerror: {error}"))
        fresh.on("console", lambda m: problems.append(f"[after check {len(checks)}] console {m.type}: {m.text}") if m.type == "error" else None)
        page.close()
        began = time.time()
        fresh.goto(args.base + "/")
        view = fresh.frame_locator("#view")
        view.locator("main.page").wait_for(timeout=180000)
        print(f"first page with no connection after {time.time() - began:.1f} s (Python starting included)")
        frame = fresh.frames[1]
        check(frame.evaluate("document.documentElement.hasAttribute('data-local')"), "home is rendered on the device")
        note = view.locator(".offline-note").inner_text()
        check(note.startswith("Offline copy: data as of"), f"banner: {note}")
        if args.shots:
            fresh.screenshot(path=f"{args.shots}/{args.site}-{args.browser}-offline-home.png")

        def current():
            return fresh.frames[1]

        def open_in_frame(path):
            current().evaluate("path => { window.location.href = path; }", path)
            fresh.wait_for_function(
                "path => { const f = document.getElementById('view').contentWindow; "
                "return f.location.pathname + f.location.search === path && f.document.readyState === 'complete' "
                "&& !!f.document.querySelector('main.page'); }", arg=path, timeout=120000)
            # Let lazy images finish: Firefox logs a service worker error for each image
            # request that the next page cancels, which would hide a real one.
            current().wait_for_load_state("networkidle")

        # -- every page matches the server's
        for path in site["pages"]:
            began = time.time()
            open_in_frame(path)
            took = time.time() - began
            same = main_text(current()) == expect[path]
            on_device = current().evaluate("document.documentElement.hasAttribute('data-local')")
            check(same and on_device, f"{path} is rendered on the device and matches the server's page ({took:.2f} s)")
            if not same and args.shots:
                open(f"{args.shots}/{args.site}-diff-{path.strip('/').replace('/', '_').replace('?', '_')}.json", "w").write(
                    json.dumps({"server": expect[path], "device": main_text(current())}, indent=1))
        check(fresh.evaluate("location.pathname + location.search") == site["pages"][-1],
              "the window's address follows the page in the frame")
        check(fresh.title() == current().title() and fresh.title() != "", f"and its title: {fresh.title()}")

        # -- a link, the search box, a filter, the chart, an image
        open_in_frame("/")
        view.locator("header .nav a", has_text=site["nav"][0]).first.click()
        fresh.wait_for_function("p => document.getElementById('view').contentWindow.location.pathname === p",
                                arg=site["nav"][1], timeout=60000)
        view.locator("main.page").wait_for()
        check(True, f"a tap on {site['nav'][0]} opens {site['nav'][1]}")
        box = view.locator("#search")
        box.click()
        box.type(site["search"][0], delay=40)
        hit = view.locator("#search-results a", has_text=site["search"][1]).first
        hit.wait_for(timeout=60000)
        sub = hit.locator("small").inner_text()
        check("Saved for offline" not in sub, f"search finds {site['search'][1]} in the whole database ({sub})")
        hit.dispatch_event("mousedown")
        fresh.wait_for_function("document.getElementById('view').contentWindow.location.pathname.startsWith('/player/')",
                                timeout=60000)
        view.locator("main.page h1").first.wait_for(timeout=60000)
        check(site["search"][1] in view.locator("main.page").inner_text(), "and his page opens")
        path, selector, value, want = site["filter"]
        open_in_frame(path)
        view.locator(selector).first.select_option(value)
        fresh.wait_for_function("w => document.getElementById('view').contentWindow.location.search.includes(w)",
                                arg=want, timeout=60000)
        view.locator("main.page table tbody tr").first.wait_for(timeout=60000)
        check(True, f"changing a filter loads {want}")
        open_in_frame(site["chart"])
        fresh.wait_for_function(
            "document.getElementById('view').contentDocument.querySelectorAll('svg circle, svg image, canvas').length > 5",
            timeout=120000)
        check(True, "the chart draws from the device's data")
        open_in_frame(site["image_page"])
        loaded = current().evaluate("""async selector => {
            const images = Array.from(document.querySelectorAll(selector)).slice(0, 6);
            const out = [];
            for (const image of images) {
                image.loading = "eager";            // lazy images below the fold would never start
                image.scrollIntoView();
                if (!image.complete) await new Promise(done => { image.onload = image.onerror = done; setTimeout(done, 15000); });
                out.push(image.complete && image.naturalWidth > 1);
            }
            return out;
        }""", site["image"])
        check(loaded and all(loaded), f"images load with no connection ({sum(loaded)} of {len(loaded)} checked)")
        if args.shots:
            fresh.screenshot(path=f"{args.shots}/{args.site}-{args.browser}-offline-team.png")
        open_in_frame(site["photo"])
        shown = current().evaluate("""async () => {
            const image = document.querySelector('img.photo');
            if (!image) return false;
            if (!image.complete) await new Promise(done => { image.onload = image.onerror = done; setTimeout(done, 15000); });
            return image.isConnected && image.naturalWidth > 1;
        }""")
        check(shown, f"a current player's photo shows with no connection ({site['photo']})")
        if args.shots:
            fresh.screenshot(path=f"{args.shots}/{args.site}-{args.browser}-offline-player.png")

        # -- back, and a reload of the whole window
        fresh.go_back()
        fresh.wait_for_function("p => document.getElementById('view').contentWindow.location.pathname === p",
                                arg=site["image_page"], timeout=60000)
        check(True, "Back returns to the previous page")
        open_in_frame(site["pages"][2])
        fresh.reload()
        fresh.frame_locator("#view").locator("main.page").wait_for(timeout=180000)
        check(fresh.evaluate("document.getElementById('view').contentWindow.location.pathname + "
                             "document.getElementById('view').contentWindow.location.search") == site["pages"][2],
              "a reload with no connection comes back to the same page")

        # -- the connection returns: pages come from the server again
        offline(False)
        time.sleep(31)                      # web/sw.js rests the network for 30 s after a failure
        open_in_frame(site["pages"][0])
        check(not current().evaluate("document.documentElement.hasAttribute('data-local')"),
              "back online, the next page comes from the server")
        # That page was saved from the server after the copy was last confirmed current, so
        # with no connection again it is the saved page that shows; others still come from the copy.
        current().wait_for_load_state("networkidle")       # nothing in flight when the connection goes
        offline(True)
        open_in_frame(site["pages"][1])
        check(current().evaluate("document.documentElement.hasAttribute('data-local')"), "offline again: the copy answers")
        open_in_frame(site["pages"][0])
        check(current().evaluate("document.documentElement.hasAttribute('data-saved')"),
              "and the page just saved from the server is shown as saved, being newer")
        # A photo that is not on the device fails to load (the page then drops it); each
        # browser words that differently. Anything else is a real error.
        absent = ("Failed to load resource", "net::ERR", "Response served by service worker is an error", "Cannot load ")
        errors = [p for p in problems if not any(text in p for text in absent)]
        check(not errors, "no script errors" + (": " + " | ".join(errors[:5]) if errors else ""))
        context.close()
    failed = [text for ok, text in checks if not ok]
    print(f"{len(checks) - len(failed)} of {len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("--key", default="")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    parser.add_argument("--site", default="baseball", choices=list(SITES))
    parser.add_argument("--shots", default="")
    sys.exit(run(parser.parse_args()))
