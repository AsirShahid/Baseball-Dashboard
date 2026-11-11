"""Home-screen install and offline use: /manifest.webmanifest and /sw.js.

The service worker (web/sw.js) is served with a CONFIG line naming this deploy's
versioned static files, so every deploy changes its bytes and phones pick up the
new files on their own. The same module runs on the basketball site.
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, url_for

ROOT = Path(__file__).resolve().parent
BACKGROUND = "#0a0e15"


def register(app: Flask, *, site: str, description: str, pages: list[str], favorite_page: str,
             shortcuts: list[tuple[str, str]], image_paths=(), image_hosts=(), data_paths=()) -> None:
    """pages: endpoints kept fresh for offline use (skipped if not registered)."""
    script = (ROOT / "sw.js").read_text()
    static = ROOT / "static"

    def asset(name: str) -> str:
        return app.jinja_env.globals["asset"](name)

    def page_urls() -> list[str]:
        urls = [url_for(endpoint) for endpoint in pages if endpoint in app.view_functions]
        return urls + [favorite_page.format(favorite=app.config["FAVORITE_TEAM"])]

    @app.route("/manifest.webmanifest")
    def manifest():
        body = {
            "id": "/",
            "name": site,
            "short_name": site,
            "description": description,
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "any",
            "background_color": BACKGROUND,
            "theme_color": BACKGROUND,
            "icons": [
                {"src": asset("icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": asset("icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": asset("icons/maskable-512.png"), "sizes": "512x512", "type": "image/png",
                 "purpose": "maskable"},
            ],
            "shortcuts": [
                {"name": name, "url": url.format(favorite=app.config["FAVORITE_TEAM"]),
                 "icons": [{"src": asset("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"}]}
                for name, url in shortcuts
            ],
        }
        response = app.response_class(json.dumps(body, indent=1), mimetype="application/manifest+json")
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.route("/sw.js")
    def service_worker():
        config = {
            "site": site,
            "static": sorted(asset(path.relative_to(static).as_posix())
                             for path in static.rglob("*") if path.is_file()),
            "pages": page_urls(),
            "css": asset("app.css"),
            "imagePaths": list(image_paths),
            "imageHosts": list(image_hosts),
            "dataPaths": list(data_paths),
        }
        body = f"const CONFIG = {json.dumps(config, separators=(',', ':'))};\n{script}"
        response = app.response_class(body, mimetype="application/javascript")
        response.headers["Cache-Control"] = "no-cache"
        return response
