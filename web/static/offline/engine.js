// The offline copy's engine: a worker that runs the site's own code on this device.
//
// It loads Pyodide (Python built for WebAssembly) from the files this device holds
// (/offline/rt/, answered from the cache by web/sw.js), mounts the downloaded pieces
// of the database as read-only files under /data, unpacks the site's code into /app
// and answers page requests through Flask's test client. shell.js owns the worker and
// passes it the requests the service worker cannot send to the server.
// The same file runs on basketball.asir.dev and baseball.asir.dev; tests/test_offline.mjs
// runs start() under Node.

const META = "meta-v1";
const ACTIVE = "/__offline/manifest";       // the copy this device holds (written by sync.js)
const HELD = 48 * 1024 * 1024;              // pieces kept in memory, least recently used dropped

const BOOT = `
import importlib, json, os, sys
os.environ.update(json.loads(OFFLINE_ENV))
sys.dont_write_bytecode = True
sys.path.insert(0, "/app")
try:
    # The copy never uses the network: with a poor connection a request the site makes
    # for outside data (a photo, a game feed) would hold every page up until it timed out.
    import requests
    def _no_network(self, method, url, *args, **kwargs):
        raise requests.ConnectionError("the offline copy does not use the network")
    requests.Session.request = _no_network
except ImportError:
    pass
_module, _name = OFFLINE_ENTRY.split(":")
_client = getattr(importlib.import_module(_module), _name)().test_client()

def offline_handle(method, target):
    response = _client.open(target, method=method)
    return response.status_code, [[key, value] for key, value in response.headers.items()], response.get_data()
`;

// A read-only file system over the pieces. A file is its list of piece hashes;
// readPiece(sha) returns one piece's bytes. SQLite reads a page at a time, so whole
// pieces are kept in memory up to budget bytes.
export function pieceFs(FS, files, readPiece, budget = HELD) {
  const held = new Map();
  let bytes = 0;
  function piece(sha) {
    let data = held.get(sha);
    if (data) {
      held.delete(sha);
      held.set(sha, data);
      return data;
    }
    data = readPiece(sha);
    held.set(sha, data);
    bytes += data.length;
    for (const [old, was] of held) {
      if (bytes <= budget || old === sha) break;
      held.delete(old);
      bytes -= was.length;
    }
    return data;
  }
  const DIR = 0o40555, FILE = 0o100444;
  const readOnly = () => { throw new FS.ErrnoError(63); };
  const fs = {
    mount() {
      const root = make(null, "/", DIR);
      for (const file of files) {
        const names = file.path.split("/");
        let folder = root;
        for (const name of names.slice(0, -1)) folder = folder.contents[name] || make(folder, name, DIR);
        const node = make(folder, names[names.length - 1], FILE);
        node.size = file.size;
        node.file = file;
      }
      return root;
    },
    node_ops: {
      getattr(node) {
        return {
          dev: 1, ino: node.id, mode: node.mode, nlink: 1, uid: 0, gid: 0, rdev: 0, size: node.size,
          atime: new Date(node.atime), mtime: new Date(node.mtime), ctime: new Date(node.ctime),
          blksize: 4096, blocks: Math.ceil(node.size / 4096),
        };
      },
      setattr() {},
      lookup() { throw new FS.ErrnoError(44); },
      readdir(node) { return [".", ".."].concat(Object.keys(node.contents)); },
      mknod: readOnly, rename: readOnly, unlink: readOnly, rmdir: readOnly, symlink: readOnly,
    },
    stream_ops: {
      read(stream, buffer, offset, length, position) {
        const node = stream.node, file = node.file;
        if (!file || position >= node.size) return 0;
        length = Math.min(length, node.size - position);
        let done = 0;
        while (done < length) {
          const at = position + done;
          const data = piece(file.chunks[Math.floor(at / file.chunkSize)]);
          const inside = at % file.chunkSize;
          const count = Math.min(length - done, data.length - inside);
          if (count <= 0) throw new FS.ErrnoError(29);      // a piece shorter than the manifest says
          buffer.set(data.subarray(inside, inside + count), offset + done);
          done += count;
        }
        return done;
      },
      write() { throw new FS.ErrnoError(63); },
      llseek(stream, offset, whence) {
        let position = offset;
        if (whence === 1) position += stream.position;
        else if (whence === 2 && FS.isFile(stream.node.mode)) position += stream.node.size;
        if (position < 0) throw new FS.ErrnoError(28);
        return position;
      },
    },
  };
  function make(parent, name, mode) {
    const node = FS.createNode(parent, name, mode, 0);
    node.node_ops = fs.node_ops;
    node.stream_ops = fs.stream_ops;
    node.atime = node.mtime = node.ctime = Date.now();
    node.size = 4096;
    node.contents = {};
    if (parent) parent.contents[name] = node;
    return node;
  }
  return fs;
}

// Start Python and the site. options: manifest, loadPyodide, indexURL, packages (wheel
// URLs), readPiece(sha) -> Uint8Array, assetVersion, report(text).
export async function start(options) {
  const manifest = options.manifest, report = options.report || (() => {});
  report("Starting Python");
  const pyodide = await options.loadPyodide({ indexURL: options.indexURL });
  report("Loading its libraries");
  await pyodide.loadPackage(options.packages, { messageCallback() {} });
  report("Opening the database");
  const data = manifest.files.filter(file => file.kind === "data").map(file => (
    { path: file.name, size: file.size, chunkSize: manifest.chunk_size, chunks: file.chunks }));
  pyodide.FS.mkdirTree("/data");
  pyodide.FS.mount(pieceFs(pyodide.FS, data, options.readPiece), {}, "/data");
  pyodide.FS.mkdirTree("/app");
  for (const file of manifest.files.filter(entry => entry.kind === "bundle")) {
    const whole = new Uint8Array(file.size);
    let at = 0;
    for (const sha of file.chunks) {
      const part = options.readPiece(sha);
      whole.set(part, at);
      at += part.length;
    }
    pyodide.unpackArchive(whole, "zip", { extractDir: "/app" });
  }
  report("Starting the site");
  const env = Object.assign({}, manifest.env, { DATA_ROOT: "/data", ASSET_VERSION: options.assetVersion || "" });
  pyodide.globals.set("OFFLINE_ENV", JSON.stringify(env));
  pyodide.globals.set("OFFLINE_ENTRY", manifest.entry);
  pyodide.runPython(BOOT);
  const handle = pyodide.globals.get("offline_handle");
  return {
    pyodide,
    // -> { status, headers: [[name, value]], body: Uint8Array }
    request(method, url) {
      const target = new URL(url, "http://offline.invalid");
      const result = handle(method, target.pathname + target.search);
      const [status, headers, body] = result.toJs({ create_pyproxies: false });
      result.destroy();
      return { status, headers, body };
    },
  };
}

// ------------------------------------------------------------------ in the browser

async function boot(report) {
  const saved = await (await caches.open(META)).match(ACTIVE);
  if (!saved) throw new Error("This device has no offline copy yet. Open About while online to download it.");
  const manifest = await saved.json();
  // Held for as long as this worker lives, so sync.js does not delete pieces in use.
  if (navigator.locks) navigator.locks.request("offline-engine", { mode: "shared" }, () => new Promise(() => {}));
  report("Reading the offline copy");
  const root = await navigator.storage.getDirectory();
  const folder = await (await root.getDirectoryHandle("offline")).getDirectoryHandle("chunks");
  const wanted = Array.from(new Set(manifest.files.flatMap(file => file.chunks)));
  const files = new Map();
  for (let i = 0; i < wanted.length; i += 64) {
    await Promise.all(wanted.slice(i, i + 64).map(async sha => {
      files.set(sha, await (await folder.getFileHandle(sha)).getFile());
    }));
  }
  const reader = new FileReaderSync();
  const base = new URL(manifest.runtime.base, self.location.href).href;
  const { loadPyodide } = await import(base + "pyodide.mjs");
  const engine = await start({
    manifest, loadPyodide, indexURL: base, report,
    packages: manifest.runtime.packages.map(name => base + name),
    readPiece: sha => new Uint8Array(reader.readAsArrayBuffer(files.get(sha))),
    assetVersion: new URL(self.location.href).searchParams.get("v") || "",
  });
  engine.manifest = manifest;
  return engine;
}

function refusal(text) {
  const page = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">`
    + `<meta name="color-scheme" content="dark"><title>Offline copy</title>`
    + `<body style="font:15px system-ui;background:#0a0e15;color:#e6e9ef;padding:24px">`
    + `<h1 style="font-size:20px">The offline copy could not answer</h1><p>${String(text).replace(/[&<>]/g, "")}</p>`;
  return { status: 503, headers: [["content-type", "text/html; charset=utf-8"]], body: new TextEncoder().encode(page) };
}

if (typeof WorkerGlobalScope !== "undefined" && self instanceof WorkerGlobalScope) {
  let engine = null, failed = null;
  const waiting = [];
  const answer = message => {
    let out;
    try {
      out = failed ? refusal(failed) : engine.request(message.method, message.url);
    } catch (error) {
      out = refusal(error && error.message || error);
    }
    self.postMessage({ type: "response", id: message.id, status: out.status, headers: out.headers,
      body: out.body.buffer }, [out.body.buffer]);
  };
  self.onmessage = event => {
    const message = event.data || {};
    if (message.type !== "request") return;
    if (engine || failed) answer(message);
    else waiting.push(message);
  };
  const began = Date.now();
  boot(text => self.postMessage({ type: "progress", text })).then(ready => {
    engine = ready;
    self.postMessage({ type: "ready", built: ready.manifest.built_at, version: ready.manifest.version,
      ms: Date.now() - began });
  }).catch(error => {
    failed = String(error && error.message || error);
    self.postMessage({ type: "failed", error: failed });
  }).then(() => { waiting.splice(0).forEach(answer); });
}
