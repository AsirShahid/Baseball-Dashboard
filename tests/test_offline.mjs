// Run with: node tests/test_offline.mjs <pack folder> <runtime folder> <path> [<path> ...]
// Starts the offline copy's engine (web/static/offline/engine.js) the way a device does,
// from a pack built by web/offline.py, and requests each path. Prints one JSON line:
// { seconds, pages: { path: { status, type, sha256, bytes, location } } }.
// tests/test_offline.py compares that with the same pages rendered by the server code.
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import zlib from "node:zlib";

const [pack, runtime, ...paths] = process.argv.slice(2);
const here = path.dirname(new URL(import.meta.url).pathname);
const { start } = await import(pathToFileURL(path.join(here, "..", "web", "static", "offline", "engine.js")).href);
const { loadPyodide } = await import(pathToFileURL(path.join(runtime, "pyodide.mjs")).href);

const manifest = JSON.parse(fs.readFileSync(path.join(pack, "manifest.json"), "utf8"));
let reads = 0;
function readPiece(sha) {
  reads += 1;
  const file = path.join(pack, "chunks", sha);
  const data = fs.existsSync(file) ? fs.readFileSync(file) : zlib.gunzipSync(fs.readFileSync(file + ".gz"));
  if (createHash("sha256").update(data).digest("hex") !== sha) throw new Error(`piece ${sha} does not match its name`);
  return new Uint8Array(data.buffer, data.byteOffset, data.length);
}

const began = Date.now();
const engine = await start({
  manifest, loadPyodide, indexURL: runtime + path.sep, readPiece, assetVersion: "test",
  packages: manifest.runtime.packages.map(name => path.join(runtime, name)),
});
const started = (Date.now() - began) / 1000;
const pages = {};
for (const target of paths) {
  const at = Date.now();
  const out = engine.request("GET", target);
  const headers = Object.fromEntries(out.headers.map(([name, value]) => [name.toLowerCase(), value]));
  pages[target] = {
    status: out.status, type: headers["content-type"] || "", location: headers.location || "",
    bytes: out.body.length, sha256: createHash("sha256").update(out.body).digest("hex"),
    seconds: (Date.now() - at) / 1000,
  };
  if (process.env.OFFLINE_DUMP) {
    fs.writeFileSync(path.join(process.env.OFFLINE_DUMP, encodeURIComponent(target)), out.body);
  }
}
console.log(JSON.stringify({ seconds: started, reads, pages }));
