"""The full offline copy (web/offline.py, web/static/offline/).

The pack is built from the fixture database. Where Node and the runtime
(web/offline_rt/, fetched by `python web/offline.py fetch-runtime`) are present, the
engine is started as a device starts it and its pages are compared with the server's.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

from web import offline  # noqa: E402

RUNTIME = offline.runtime_files(offline.FLASK + ["numpy"]) is not None
needs_runtime = pytest.mark.skipif(not RUNTIME, reason="offline runtime not fetched")
KEY = "s3cret"


@pytest.fixture(scope="module")
def data_root(tmp_path_factory):
    from pipeline import build
    out = tmp_path_factory.mktemp("data")
    build.build(FIXTURES, FIXTURES, out, FIXTURES / "bwar", FIXTURES / "savant")
    return out


@pytest.fixture(scope="module")
def site(data_root, tmp_path_factory):
    """The site as deployed: the offline copy offered to holders of the key."""
    from web import create_app
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OFFLINE_KEY", KEY)
        patch.setenv("OFFLINE_ROOT", str(tmp_path_factory.mktemp("pack")))
        app = create_app(data_root)
    app.config["TESTING"] = True
    return app


@pytest.fixture(scope="module")
def pack(site):
    return site.extensions["offline"]


@pytest.fixture(scope="module")
def manifest(pack):
    if not RUNTIME:
        pytest.skip("offline runtime not fetched")
    return pack.build()


def piece(pack, sha):
    path, packed = pack.chunk(sha)
    data = path.read_bytes()
    return gzip.decompress(data) if packed else data


@needs_runtime
def test_pieces_rebuild_every_file(pack, manifest, data_root):
    by_name = {entry["name"]: entry for entry in manifest["files"]}
    assert set(by_name) == {"baseball.sqlite", "app.zip", "logos.zip"}
    database = by_name["baseball.sqlite"]
    assert database["kind"] == "data" and database["size"] == (data_root / "baseball.sqlite").stat().st_size
    whole = b"".join(piece(pack, sha) for sha in database["chunks"])
    assert whole == (data_root / "baseball.sqlite").read_bytes()
    for entry in manifest["files"]:
        for index, sha in enumerate(entry["chunks"]):
            data = piece(pack, sha)
            assert hashlib.sha256(data).hexdigest() == sha
            last = index == len(entry["chunks"]) - 1
            assert len(data) == (entry["size"] - offline.CHUNK * index if last else offline.CHUNK)
    assert manifest["bytes"] >= manifest["download"] > 0
    assert manifest["runtime"]["version"] == offline.RUNTIME_VERSION
    assert {f["name"] for f in manifest["runtime"]["files"]} >= set(offline.CORE)


@needs_runtime
def test_code_bundle_holds_the_site_and_no_secrets(pack, manifest):
    import io
    import zipfile
    entry = next(e for e in manifest["files"] if e["name"] == "app.zip")
    names = zipfile.ZipFile(io.BytesIO(b"".join(piece(pack, sha) for sha in entry["chunks"]))).namelist()
    assert {"app.py", "web/__init__.py", "web/templates/base.html", "pipeline/teams.py"} <= set(names)
    assert not [n for n in names if "__pycache__" in n or n.startswith(("web/static/", "web/offline_rt/"))
                or n.endswith((".pyc", ".env")) or "cookie" in n.lower()]


@needs_runtime
def test_unchanged_sources_build_the_same_copy(pack, manifest):
    assert pack.fresh(pack.manifest())
    before = {p.name for p in (pack.root / "chunks").iterdir()}
    again = pack.build()
    assert again["version"] == manifest["version"]
    assert {p.name for p in (pack.root / "chunks").iterdir()} == before


@needs_runtime
def test_routes_need_the_key(site, manifest, data_root, monkeypatch):
    from web import create_app
    monkeypatch.delenv("OFFLINE_KEY", raising=False)
    closed = create_app(data_root).test_client()        # no key set: the copy is not offered at all
    assert closed.get("/offline/manifest.json").status_code == 404
    assert 'id="offline-card"' not in closed.get("/about").get_data(as_text=True)
    assert json.loads(closed.get("/sw.js").get_data(as_text=True).split("\n", 1)[0][len("const CONFIG = "):-1])["offline"] is None

    client = site.test_client()
    sha = manifest["files"][0]["chunks"][0]
    runtime = f"/offline/rt/{offline.RUNTIME_VERSION}/pyodide.mjs"
    for url in ("/offline/manifest.json", f"/offline/chunk/{sha}", runtime):
        assert client.get(url).status_code == 404, url
        assert client.get(url, headers={"X-Offline-Key": "wrong"}).status_code == 404, url
    key = {"X-Offline-Key": KEY}
    served = client.get("/offline/manifest.json", headers=key)
    body = served.get_json()
    assert served.headers["Cache-Control"] == "no-store"
    assert body["version"] == manifest["version"] and "stamp" not in body and body["building"] is False
    # This season's players' photos, as the player page asks for them.
    group = body["photos"]["groups"][0]
    assert body["photos"]["count"] == len(group["ids"]) > 0 and body["photos"]["bytes"] == group["each"] * len(group["ids"])
    player = client.get("/player/15640").get_data(as_text=True)          # Aaron Judge, in the latest season
    assert "{id}" in group["url"] and any(group["url"].replace("{id}", str(i)) in player for i in group["ids"])
    plain = client.get(f"/offline/chunk/{sha}", headers=key)
    packed = client.get(f"/offline/chunk/{sha}", headers={**key, "Accept-Encoding": "gzip"})
    assert plain.status_code == packed.status_code == 200
    assert hashlib.sha256(plain.get_data()).hexdigest() == sha
    data = packed.get_data()
    assert hashlib.sha256(gzip.decompress(data) if packed.headers.get("Content-Encoding") == "gzip" else data).hexdigest() == sha
    module = client.get(runtime, headers=key)
    assert module.status_code == 200 and module.mimetype == "text/javascript"
    assert client.get(f"/offline/rt/{offline.RUNTIME_VERSION}/pyodide.asm.wasm", headers=key).mimetype == "application/wasm"
    for bad in ("/offline/chunk/" + "g" * 64, "/offline/chunk/abc", "/offline/rt/0/pyodide.mjs",
                f"/offline/rt/{offline.RUNTIME_VERSION}/..%2Foffline.py"):
        assert client.get(bad, headers=key).status_code == 404, bad
    about = client.get("/about").get_data(as_text=True)
    assert 'id="offline-card"' in about and 'data-access="key"' in about and "offline/ui.js" in about
    config = json.loads(client.get("/sw.js").get_data(as_text=True).split("\n", 1)[0][len("const CONFIG = "):-1])
    assert config["offline"]["engine"] in config["static"] and config["offline"]["shell"] in config["static"]


PAGES = ["/", "/standings", "/players", f"/player/{15640}", "/team/NYY", "/players?kind=pit&mode=advanced",
         "/teams?season=1955", "/players?season=1955&to=2024", "/compare?p=15640,19755", "/chart",
         "/api/search?q=judge", "/api/chart?view=player&kind=bat&x=wRC%2B&y=WAR", "/nope",
         "/?view=team&x_stat=WAR"]


@needs_runtime
def test_the_device_renders_the_servers_pages(pack, manifest, site):
    """tests/test_offline.mjs starts the engine from the pack; each page must be the server's."""
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        pytest.skip("node not installed")
    done = subprocess.run([node, str(ROOT / "tests" / "test_offline.mjs"), str(pack.root), str(offline.RUNTIME_DIR), *PAGES],
                          capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    client = site.test_client()
    version = re.compile(rb"\?v=[0-9a-z]+")
    for path in PAGES:
        ours, theirs = client.get(path), result["pages"][path]
        assert theirs["status"] == ours.status_code, path
        assert theirs["type"] == ours.headers["Content-Type"], path
        if ours.status_code in (301, 302, 308):
            assert theirs["location"] == ours.headers["Location"], path
            continue
        # The only difference allowed is the static files' version, which the device supplies.
        body = version.sub(b"?v=test", ours.get_data())
        assert theirs["sha256"] == hashlib.sha256(body).hexdigest(), path
