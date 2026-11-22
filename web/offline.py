"""The full offline copy: /offline/.

A phone or tablet can hold the whole site: the SQLite files, this site's own Python
code, and Pyodide (Python built for WebAssembly) to run it. With no connection,
web/sw.js hands pages to that copy instead of the server (web/static/offline/), so
every page, tab and filter works. The same module runs on the basketball and
baseball sites.

The server's part is three routes:

  /offline/manifest.json    what the copy consists of, as lists of piece hashes
  /offline/chunk/<sha256>   one 256 KB piece of a file (gzip when that is smaller)
  /offline/rt/<version>/..  Pyodide and the wheels, fetched into web/offline_rt/
                            when the image is built (python web/offline.py fetch-runtime)

Files are cut into fixed pieces named by their SHA-256, so a device downloads only
the pieces it lacks: a refresh that rewrites one season costs that season's pieces,
an interrupted download resumes, and every piece is checked on arrival. The pieces
are built on demand under OFFLINE_ROOT (the container's own disk) by
`python web/offline.py build`, which the manifest route starts when a source file
has changed. The updaters replace a database by renaming a new file over it, so
reading one open file is a consistent snapshot.

access="key" keeps the copy to devices that hold OFFLINE_KEY (sent as X-Offline-Key);
without the variable the routes answer 404. The baseball site is public, and a
ready-made database is not something to hand to every visitor.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import hmac
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT / "offline_rt"
FORMAT = 1
CHUNK = 256 * 1024
SMALLER = 0.9                      # keep the gzip form only when it is under 90% of the piece
KEEP_SECONDS = 3600                # pieces no manifest names any more stay this long

RUNTIME_VERSION = "314.0.8"
RUNTIME_SOURCE = f"https://cdn.jsdelivr.net/pyodide/v{RUNTIME_VERSION}/full/"
CORE = {
    "pyodide.mjs": "1bb8cc14f9405aaa7cd4e00c12edd0a8539de9cc026618d6ee5a9663f367dc70",
    "pyodide.asm.mjs": "22514b8be6980e28a02c8b1d6387ce8dfe666fc4edf8d547cff5dce29ff4d972",
    "pyodide.asm.wasm": "e14d49ceca9b4a0e274ea918f3a898de2d3880b6e5573a6cfe1a2267ecc70329",
    "python_stdlib.zip": "2bd3394a145bfbbe5bbc9d9d6ab9136abbb986c6fef6c142b3a2962227aa5c28",
    "pyodide-lock.json": "5dc2fc119108bc148c7457dc86e7675b5c87e1cafd420b9c34c1eaef7b36c010",
}
_PYPI = "https://files.pythonhosted.org/packages/"
# package: (wheel, sha256, where from; None = the Pyodide distribution)
WHEELS = {
    "numpy": ("numpy-2.4.6-cp314-cp314-pyemscripten_2026_0_wasm32.whl",
              "a292c1f5d7d8a2208cd5e94fc467604c131cabcd2fc14fed6eefde121e7fabdf", None),
    "tzdata": ("tzdata-2025.3-py2.py3-none-any.whl",
               "9ce669f4f075843c7ff6a3f3dc306ebafa504717ec7beb6aa2233693722ddcfc", None),
    "markupsafe": ("markupsafe-3.0.3-cp314-cp314-pyemscripten_2026_0_wasm32.whl",
                   "b44c364dc0d19e4210ce68ab77833c2b5d608f78fe6966263add4fc1fa667d97", None),
    "jinja2": ("jinja2-3.1.6-py3-none-any.whl",
               "9330ec9cf2241fb8fc352928ea5e72016bf82de1d3d3b71ffea52a093a3ebab8", None),
    "click": ("click-8.3.1-py3-none-any.whl",
              "d3118144289833a6a3868e953a63a57f6166b33497e1cbe6231423de27465f78", None),
    "requests": ("requests-2.33.1-py3-none-any.whl",
                 "6d62c51c4e7707386bfc2ef54845c16cdaeb99606c064357cccfe4d621285175", None),
    "certifi": ("certifi-2026.4.22-py3-none-any.whl",
                "c2c0091986db798df5fd84582d289496f31244a898ec032b7015278c2d82c80c", None),
    "charset-normalizer": ("charset_normalizer-3.4.7-py3-none-any.whl",
                           "9e437ef92fa51f06eedeb1ef092c0a887bd24fe0d40b1e900191117ce1653121", None),
    "idna": ("idna-3.11-py3-none-any.whl",
             "1619419bc899f07c7a608a12e8238e5e0bc15bb25fec90cfe20a86bb849ba0d8", None),
    "urllib3": ("urllib3-2.6.3-py3-none-any.whl",
                "86b7c1af060597b115bcde5e36798039ca50b221afe14aa03d3437ac09b02a75", None),
    "flask": ("flask-3.1.3-py3-none-any.whl",
              "f4bcbefc124291925f1a26446da31a5178f9483862233b23c0c96a20701f670c",
              _PYPI + "7f/9c/34f6962f9b9e9c71f6e5ed806e0d0ff03c9d1b0b2340088a0cf4bce09b18/"),
    "werkzeug": ("werkzeug-3.1.9-py3-none-any.whl",
                 "6392e50c78460ba618e5b21f08a71f59c99ce99cdc6cf6e3dd7e6ccca8754fab",
                 _PYPI + "a1/38/df03f564f43cec2684823f3cccae1a652ee7face1cbaa76fb223096e64d7/"),
    "itsdangerous": ("itsdangerous-2.2.0-py3-none-any.whl",
                     "c6242fc49e35958c8b15141343aa660db5fc54d4f13a1db01a3f5891b98700ef",
                     _PYPI + "04/96/92447566d16df59b2a776c0fb82dbc4d9e07cd95062562af01e408583fc4/"),
    "blinker": ("blinker-1.9.0-py3-none-any.whl",
                "ba0efaa9080b619ff2f3459d1d500c57bddea4a6b424b60a91141db6fd2f08bc",
                _PYPI + "10/cb/f2ad4230dc2eb1a74edf38f1a38b9b52277f75bef262d8908e60d957e13c/"),
}
FLASK = ["markupsafe", "jinja2", "click", "blinker", "itsdangerous", "werkzeug", "flask", "tzdata"]
REQUESTS = ["certifi", "charset-normalizer", "idna", "urllib3", "requests"]
_TYPES = {".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm",
          ".json": "application/json", ".zip": "application/zip", ".whl": "application/zip"}
_SKIP_DIRS = {"__pycache__", "static", "offline_rt", "vendor", ".pytest_cache"}

log = logging.getLogger("offline")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# ------------------------------------------------------------------ the runtime

def fetch_runtime(target: Path = RUNTIME_DIR) -> int:
    """Download Pyodide and every wheel into ``target``, checking each SHA-256."""
    import urllib.request
    target.mkdir(parents=True, exist_ok=True)
    wanted = {name: (RUNTIME_SOURCE, sha) for name, sha in CORE.items()}
    wanted.update({wheel: (source or RUNTIME_SOURCE, sha) for wheel, sha, source in WHEELS.values()})
    total = 0
    for name, (source, sha) in sorted(wanted.items()):
        path = target / name
        if not (path.exists() and _sha(path.read_bytes()) == sha):
            request = urllib.request.Request(source + name, headers={"User-Agent": "offline-runtime-fetch"})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            if _sha(data) != sha:
                raise SystemExit(f"{name}: SHA-256 {_sha(data)} is not the pinned {sha}")
            _write(path, data)
        total += path.stat().st_size
    print(f"offline runtime {RUNTIME_VERSION}: {len(wanted)} files, {total / 1e6:.1f} MB in {target}")
    return total


def runtime_files(packages) -> list[dict] | None:
    """The runtime files a site with these packages needs, or None when one is missing."""
    names = list(CORE) + [WHEELS[package][0] for package in packages]
    try:
        return [{"name": name, "size": (RUNTIME_DIR / name).stat().st_size} for name in names]
    except OSError:
        return None


# ------------------------------------------------------------------ the pieces

def _zip(parts) -> bytes:
    """A stored, repeatable zip of [(folder or file name inside the copy, path on disk)]."""
    entries = []
    for prefix, source in parts:
        source = Path(source)
        if source.is_file():
            entries.append((prefix, source))
            continue
        for folder, dirs, files in os.walk(source):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
            for name in sorted(files):
                if name.endswith(".pyc"):
                    continue
                path = Path(folder) / name
                entries.append((f"{prefix}/{path.relative_to(source).as_posix()}", path))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, path in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


class Pack:
    """One site's offline copy on the server: the pieces and the manifest naming them."""

    def __init__(self, *, site, entry, data_files, bundles, packages, env, root=None):
        self.site, self.entry = site, entry
        self.data_files, self.bundles = data_files, bundles      # both callables
        self.packages, self.env = list(packages), env            # env is a callable
        self.root = Path(root or os.environ.get("OFFLINE_ROOT")
                         or Path(tempfile.gettempdir()) / "offline-pack" / site.lower())
        self._code = (0.0, None)

    # What the copy is made from, cheaply: the data files by identity, the code by its files.
    def stamp(self) -> list:
        out = []
        for name, path in self.data_files():
            stat = Path(path).stat()
            out.append([name, stat.st_ino, stat.st_mtime_ns, stat.st_size])
        if time.time() - self._code[0] > 60:
            seen = hashlib.sha256()
            for _name, parts in sorted(self.bundles().items()):
                for prefix, source in parts:
                    paths = [Path(source)] if Path(source).is_file() else sorted(
                        p for p in Path(source).rglob("*")
                        if p.is_file() and not (_SKIP_DIRS & set(p.relative_to(source).parts)))
                    for path in paths:
                        stat = path.stat()
                        seen.update(f"{prefix}|{path.name}|{stat.st_mtime_ns}|{stat.st_size}\n".encode())
            self._code = (time.time(), seen.hexdigest()[:16])
        out.append(["code", self._code[1], RUNTIME_VERSION, sorted(self.packages), self.env()])
        return out

    def manifest(self) -> dict | None:
        try:
            return json.loads((self.root / "manifest.json").read_text())
        except (OSError, ValueError):
            return None

    def fresh(self, manifest) -> bool:
        try:
            return bool(manifest) and manifest.get("stamp") == json.loads(json.dumps(self.stamp()))
        except OSError:
            return True      # a source is missing right now (being replaced): keep what there is

    def _cut(self, name: str, handle, new: dict, **extra) -> dict:
        chunks, size, stored = [], 0, 0
        folder = self.root / "chunks"
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            sha = _sha(block)
            raw, packed = folder / sha, folder / (sha + ".gz")
            if not raw.exists() and not packed.exists():
                small = gzip.compress(block, 6, mtime=0)
                if len(small) < len(block) * SMALLER:
                    _write(packed, small)
                else:
                    _write(raw, block)
                new[sha] = min(len(small), len(block))
            stored += (packed if packed.exists() else raw).stat().st_size
            chunks.append(sha)
            size += len(block)
        return {"name": name, "size": size, "download": stored, "chunks": chunks, **extra}

    def build(self) -> dict | None:
        """Cut every file into pieces and write the manifest. None when another build holds the lock."""
        runtime = runtime_files(self.packages)
        if runtime is None:
            raise RuntimeError(f"offline runtime missing in {RUNTIME_DIR}: run python web/offline.py fetch-runtime")
        (self.root / "chunks").mkdir(parents=True, exist_ok=True)
        with open(self.root / ".lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return None
            started = time.time()
            before = self.manifest()
            stamp, files, new, newest = [], [], {}, 0
            for name, path in self.data_files():
                with open(path, "rb") as handle:
                    stat = os.fstat(handle.fileno())
                    stamp.append([name, stat.st_ino, stat.st_mtime_ns, stat.st_size])
                    newest = max(newest, stat.st_mtime)
                    files.append(self._cut(name, handle, new, kind="data"))
            self._code = (0.0, None)
            stamp.append(self.stamp()[-1])
            for name, parts in sorted(self.bundles().items()):
                files.append(self._cut(name, io.BytesIO(_zip(parts)), new, kind="bundle"))
            body = {
                "format": FORMAT, "site": self.site, "entry": self.entry, "env": self.env(),
                "chunk_size": CHUNK, "files": files,
                "runtime": {"version": RUNTIME_VERSION, "base": f"/offline/rt/{RUNTIME_VERSION}/",
                            "files": runtime, "packages": [WHEELS[p][0] for p in self.packages]},
            }
            body["version"] = _sha(json.dumps(body, sort_keys=True).encode())[:16]
            body["built_at"] = datetime.fromtimestamp(newest, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            body["bytes"] = sum(f["size"] for f in files) + sum(f["size"] for f in runtime)
            body["download"] = sum(f["download"] for f in files) + sum(f["size"] for f in runtime)
            body["stamp"] = stamp
            _write(self.root / "manifest.json", json.dumps(body, separators=(",", ":")).encode())
            named = {sha for f in files for sha in f["chunks"]}
            had = {sha for f in (before or {}).get("files", []) for sha in f["chunks"]}
            for path in (self.root / "chunks").iterdir():
                if path.name.split(".")[0] not in named and not path.name.startswith(".") \
                        and time.time() - path.stat().st_mtime > KEEP_SECONDS:
                    path.unlink(missing_ok=True)
            fresh = named - had if before else named
            print(f"offline copy {body['version']}: {len(named)} pieces, {body['download'] / 1e6:.1f} MB to download; "
                  f"{len(fresh)} pieces differ from the previous copy "
                  f"({sum(new.get(sha, 0) for sha in fresh) / 1e6:.1f} MB of them newly stored); "
                  f"built in {time.time() - started:.1f} s", flush=True)
            return body

    def building(self) -> bool:
        """True while a build holds the lock."""
        try:
            with open(self.root / ".lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            return isinstance(error, BlockingIOError)
        return False

    def start_build(self) -> None:
        """Build in a separate small process (this file run as a script, so it does not
        load the site), so a page never waits for it and it costs the site little memory."""
        self._children = [child for child in getattr(self, "_children", []) if child.poll() is None]
        if self._children or self.building():
            return
        config = {"site": self.site, "entry": self.entry, "root": str(self.root), "packages": self.packages,
                  "env": self.env(), "data_files": [[name, str(path)] for name, path in self.data_files()],
                  "bundles": {name: [[prefix, str(path)] for prefix, path in parts]
                              for name, parts in self.bundles().items()}}
        try:
            child = subprocess.Popen([sys.executable, str(ROOT / "offline.py"), "build", "--config", "-"],
                                     stdin=subprocess.PIPE, start_new_session=True)
            child.stdin.write(json.dumps(config).encode())
            child.stdin.close()
            self._children.append(child)
        except OSError:
            log.exception("offline copy build not started")

    def chunk(self, sha: str):
        """(path, gzipped) for a piece, or None."""
        packed = self.root / "chunks" / (sha + ".gz")
        if packed.exists():
            return packed, True
        raw = self.root / "chunks" / sha
        return (raw, False) if raw.exists() else None


# ------------------------------------------------------------------ the routes

def register(app, *, site: str, data_files, bundles, packages, env, entry: str = "web:create_app",
             access: str = "open", photos=None) -> None:
    """data_files: -> [(path under the data root, file on disk)], the files the site reads.
    bundles: -> {zip name: [(name inside /app, file or folder on disk)]}, unpacked into /app.
    packages: the wheels the site imports (keys of WHEELS). env: -> variables create_app reads.
    photos: -> [{"url": "...{id}...", "ids": [...], "each": bytes}], the player photos a device
    keeps as well (this season's players), exactly as the pages ask for them. The device
    fetches them itself after the copy; they are not pieces and do not change its version.
    """
    from flask import abort, request, send_file

    if sys.platform == "emscripten":          # this is the copy itself, running on a device
        app.jinja_env.globals["offline_card"] = {"access": "local", "site": site}
        return
    key = os.environ.get("OFFLINE_KEY", "")
    if os.environ.get("OFFLINE_ACCESS") in ("open", "key", "off"):
        access = os.environ["OFFLINE_ACCESS"]
    if access == "key" and not key:
        access = "off"
    pack = Pack(site=site, entry=entry, data_files=data_files, bundles=bundles, packages=packages, env=env)
    app.extensions["offline"] = pack
    app.jinja_env.globals["offline_card"] = {"access": access, "site": site}

    def allowed() -> bool:
        if access == "open":
            return True
        return access == "key" and hmac.compare_digest(request.headers.get("X-Offline-Key", ""), key)

    def private(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    listed = [0.0, None]

    def photo_list():
        if photos is None:
            return None
        if time.time() - listed[0] > 600:
            try:
                groups = [g for g in photos() if g["ids"]]
                listed[:] = [time.time(), {"groups": groups, "count": sum(len(g["ids"]) for g in groups),
                                           "bytes": sum(len(g["ids"]) * g.get("each", 0) for g in groups)}]
            except Exception:              # the database is being replaced: no list this time
                log.exception("offline photo list")
        return listed[1]

    @app.route("/offline/manifest.json")
    def offline_manifest():
        if not allowed():
            abort(404)
        if runtime_files(pack.packages) is None:
            return private(app.response_class('{"error":"runtime"}', status=503, mimetype="application/json"))
        manifest = pack.manifest()
        building = not pack.fresh(manifest)
        if building:
            pack.start_build()
        if manifest is None:
            return private(app.response_class('{"building":true}', status=202, mimetype="application/json"))
        manifest.pop("stamp", None)
        manifest["building"] = building
        if photo_list():
            manifest["photos"] = photo_list()
        return private(app.response_class(json.dumps(manifest, separators=(",", ":")), mimetype="application/json"))

    @app.route("/offline/chunk/<sha>")
    def offline_chunk(sha: str):
        if not allowed() or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            abort(404)
        found = pack.chunk(sha)
        if found is None:
            abort(404)
        path, packed = found
        if packed and "gzip" not in request.headers.get("Accept-Encoding", ""):
            response = app.response_class(gzip.decompress(path.read_bytes()), mimetype="application/octet-stream")
        else:
            response = send_file(path, mimetype="application/octet-stream")
            if packed:
                response.headers["Content-Encoding"] = "gzip"
        return private(response)

    @app.route("/offline/rt/<version>/<name>")
    def offline_runtime(version: str, name: str):
        known = set(CORE) | {wheel for wheel, _sha256, _source in WHEELS.values()}
        if not allowed() or version != RUNTIME_VERSION or name not in known:
            abort(404)
        path = RUNTIME_DIR / name
        if not path.exists():
            abort(404)
        return private(send_file(path, mimetype=_TYPES.get(path.suffix, "application/octet-stream")))


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="The full offline copy")
    parser.add_argument("command", choices=["fetch-runtime", "build"])
    parser.add_argument("--config", help="'-' reads the site's settings as JSON from standard input "
                                         "(how the site starts a build); without it the site is loaded")
    args = parser.parse_args(argv)
    if args.command == "fetch-runtime":
        fetch_runtime()
        return 0
    if args.config == "-":
        c = json.load(sys.stdin)
        pack = Pack(site=c["site"], entry=c["entry"], packages=c["packages"], env=lambda: c["env"], root=c["root"],
                    data_files=lambda: [(name, Path(path)) for name, path in c["data_files"]],
                    bundles=lambda: {name: [(prefix, Path(path)) for prefix, path in parts]
                                     for name, parts in c["bundles"].items()})
    else:
        sys.path.insert(0, str(ROOT.parent))
        from web import create_app
        pack = create_app().extensions.get("offline")
        if pack is None:
            print("offline copy is not set up for this site")
            return 1
    if pack.build() is None:
        print("another build is running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
