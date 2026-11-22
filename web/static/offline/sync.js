// The offline copy's downloader: a worker that brings this device's copy up to date.
//
// The server's manifest (/offline/manifest.json, web/offline.py) lists every file as
// 256 KB pieces named by their SHA-256. This worker keeps the pieces as files in the
// browser's private file system (offline/chunks/<sha256>) and Pyodide in a cache, and
// downloads only what is missing, so an interrupted download resumes and a refresh
// costs the pieces that changed. When everything is here it records the manifest in
// the meta cache: that record is what web/sw.js and engine.js treat as "this device
// has an offline copy". ui.js starts the worker and shows its messages.
// The same file runs on basketball.asir.dev and baseball.asir.dev.
"use strict";

const META = "meta-v1";
const ACTIVE = "/__offline/manifest";
const RUNTIME = "offline-rt-";
const PHOTOS = "photos-v1";
const AT_ONCE = 6;
let stop = false;

self.onmessage = event => {
  const message = event.data || {};
  if (message.cmd === "stop") { stop = true; return; }
  const job = message.cmd === "remove" ? remove() : message.cmd === "status" ? status()
    : message.cmd === "size" ? size(message) : sync(message);
  job.catch(error => self.postMessage({ type: "state", state: "error", error: String(error && error.message || error) }));
};

function say(state, more) {
  self.postMessage(Object.assign({ type: "state", state }, more || {}));
}

async function active() {
  const saved = await (await caches.open(META)).match(ACTIVE);
  return saved ? saved.json() : null;
}

// Record the copy this device holds. x-checked is when the server last confirmed it as
// its newest: web/sw.js prefers a page saved from the server after that moment.
async function record(manifest) {
  await (await caches.open(META)).put(ACTIVE, new Response(JSON.stringify(manifest), {
    headers: { "content-type": "application/json", "x-checked": new Date().toISOString() },
  }));
}

function summary(manifest) {
  return manifest ? { version: manifest.version, built: manifest.built_at, bytes: manifest.bytes } : {};
}

// The photos a manifest lists, as absolute addresses.
function photoList(manifest) {
  const out = [];
  for (const group of (manifest && manifest.photos && manifest.photos.groups) || []) {
    for (const id of group.ids) out.push(new URL(group.url.replace("%7Bid%7D", id).replace("{id}", id), self.location.href).href);
  }
  return out;
}

// { have, total } photos on this device for a manifest's list; null when it lists none.
async function photoCount(manifest) {
  const list = photoList(manifest);
  if (!list.length) return null;
  const have = new Set((await (await caches.open(PHOTOS)).keys()).map(request => request.url));
  return { have: list.filter(url => have.has(url)).length, total: list.length };
}

async function ready(manifest) {
  say("ready", Object.assign(summary(manifest), { photos: await photoCount(manifest) }));
}

async function status() {
  const have = await active();
  if (have) await ready(have);
  else say("none");
}

// This season's players' photos, after the copy itself: each is fetched the way a page's
// <img> asks for it and kept in its own cache, which web/sw.js reads. One that fails is
// left for the next check; after a run of failures (no connection) the rest wait too.
// A drawn placeholder (the site's silhouette, an SVG, sent when the photo's source had
// none or did not answer) is kept but asked for again after a day.
const RETRY = "/__offline/photo-retry";    // in META: { address: when to ask again }
async function photos(manifest) {
  const list = photoList(manifest);
  const cache = await caches.open(PHOTOS), meta = await caches.open(META);
  const have = new Set((await cache.keys()).map(request => request.url));
  const want = new Set(list);
  for (const url of have) if (!want.has(url)) await cache.delete(url);
  const noted = await meta.match(RETRY);
  const retry = noted ? await noted.json().catch(() => ({})) : {};
  for (const url of Object.keys(retry)) if (!want.has(url)) delete retry[url];
  const queue = list.filter(url => !have.has(url) || (retry[url] && retry[url] < Date.now()));
  let done = list.length - queue.filter(url => !have.has(url)).length, failed = 0, last = Date.now(), changed = false;
  const info = summary(manifest);
  if (queue.length) say("ready", Object.assign({}, info, { photos: { have: done, total: list.length, busy: true } }));
  async function worker() {
    while (queue.length && !stop && failed < 12) {
      const url = queue.pop();
      try {
        const cross = new URL(url).origin !== self.location.origin;
        const response = await fetch(url, cross ? { mode: "cors", credentials: "omit" } : { credentials: "same-origin" });
        const kind = response.headers.get("content-type") || "";
        // Only an image is kept: an expired sign-in answers a photo's address with a page.
        if (!response.ok || !kind.startsWith("image/")) throw new Error("status " + response.status);
        const drawn = kind.includes("svg");
        await cache.put(url, response);
        if (drawn) retry[url] = Date.now() + 24 * 3600 * 1000;
        else delete retry[url];
        changed = true;
        if (!have.has(url)) done += 1;
        failed = 0;
      } catch (error) {
        failed += 1;
      }
      if (Date.now() - last > 400) {
        last = Date.now();
        say("ready", Object.assign({}, info, { photos: { have: done, total: list.length, busy: true } }));
      }
    }
  }
  if (queue.length) await Promise.all(Array.from({ length: AT_ONCE }, worker));
  if (changed) await meta.put(RETRY, new Response(JSON.stringify(retry), { headers: { "content-type": "application/json" } }));
  say("ready", Object.assign({}, info, { photos: list.length ? { have: done, total: list.length } : null }));
}

// Some browsers give a private window no file storage. Found out before offering a download.
async function storable() {
  try {
    await navigator.storage.getDirectory();
    return true;
  } catch (error) {
    return false;
  }
}

// For a device without a copy: how large the download is (and whether it is allowed).
async function size(message) {
  const have = await active();
  if (have) { await ready(have); return; }
  if (!(await storable())) { say("unable"); return; }
  const response = await get("/offline/manifest.json", message.key || "");
  if (response.status === 404) { say("locked"); return; }
  const manifest = response.status === 200 ? await response.json() : {};
  say("none", { total: manifest.download || 0, photoBytes: (manifest.photos || {}).bytes || 0 });
}

async function folder(create) {
  const root = await navigator.storage.getDirectory();
  const offline = await root.getDirectoryHandle("offline", { create });
  return offline.getDirectoryHandle("chunks", { create });
}

async function get(url, key) {
  const response = await fetch(url, { cache: "no-store", redirect: "manual", credentials: "same-origin",
    headers: key ? { "X-Offline-Key": key } : {} });
  if (response.type === "opaqueredirect") throw new Error("Sign in again, then retry.");
  return response;
}

// Every piece a manifest names -> its length in bytes.
function pieces(manifest) {
  const out = new Map();
  for (const file of manifest.files) {
    file.chunks.forEach((sha, index) => {
      const last = index === file.chunks.length - 1;
      out.set(sha, last ? file.size - manifest.chunk_size * index : manifest.chunk_size);
    });
  }
  return out;
}

// What a download of the missing pieces transfers, from each file's stored size.
function transfer(manifest, missing) {
  let total = 0;
  for (const file of manifest.files) {
    const lacking = file.chunks.filter(sha => missing.has(sha)).length;
    if (lacking) total += file.download * lacking / file.chunks.length;
  }
  return Math.round(total);
}

async function hex(buffer) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", buffer));
  return Array.from(digest, byte => byte.toString(16).padStart(2, "0")).join("");
}

// A writable stream where the browser has one: the file appears whole or not at all, and
// Safari counts its real size (it books 1 MB against the site's allowance for every file
// opened with a sync access handle until the next launch). Older Safari has only the handle.
async function store(dir, sha, buffer) {
  const handle = await dir.getFileHandle(sha, { create: true });
  if (handle.createWritable) {
    const stream = await handle.createWritable();
    try {
      await stream.write(buffer);
    } catch (error) {
      await stream.abort().catch(() => undefined);
      throw error;
    }
    await stream.close();
    return;
  }
  const access = await handle.createSyncAccessHandle();
  try {
    await access.truncate(0);
    if (access.write(new Uint8Array(buffer), { at: 0 }) !== buffer.byteLength) throw new Error("This device could not store a piece.");
    await access.flush();
  } finally {
    await access.close();
  }
}

// message: { key, auto, limit }. auto = a background check: download only when the
// missing part is at most `limit` bytes (or the connection is known to be Wi-Fi).
async function sync(message) {
  if (!navigator.locks) return run(message);
  return navigator.locks.request("offline-sync", { ifAvailable: true }, lock => {
    if (!lock) { say("busy"); return undefined; }
    return run(message);
  });
}

async function run(message) {
  stop = false;
  const key = message.key || "";
  const before = await active();
  if (!before && !(await storable())) { say("unable"); return; }
  say("checking", summary(before));
  // The server cuts the pieces after its data changes (about 15 s). A background check
  // takes what there is; a download the user asked for waits for the new copy, up to
  // 30 s when an older one is on offer and 2 minutes when there is none yet.
  let manifest = null;
  for (let tries = 0; tries < 40 && !stop; tries += 1) {
    const response = await get("/offline/manifest.json", key);
    if (response.status === 404) { say("locked"); return; }
    if (response.status === 200) {
      manifest = await response.json();
      if (!manifest.building || message.auto || tries >= 10) break;
    } else if (response.status !== 202) {
      throw new Error("The server answered " + response.status + ".");
    }
    if (message.auto) return;
    say("preparing", summary(before));
    await new Promise(resolve => setTimeout(resolve, 3000));
  }
  if (stop) return;
  if (!manifest) throw new Error("The server is still preparing the copy. Try again in a minute.");
  if (before && before.version === manifest.version) {
    if (!manifest.building) await record(manifest);     // still the server's newest: note when we saw that
    await tidy(manifest);
    await photos(manifest);
    return;
  }

  const dir = await folder(true);
  const want = pieces(manifest);
  const have = new Set();
  for await (const [name, handle] of dir.entries()) {
    if (want.has(name) && (await handle.getFile()).size === want.get(name)) have.add(name);
  }
  const missing = new Set(Array.from(want.keys()).filter(sha => !have.has(sha)));
  const cache = await caches.open(RUNTIME + manifest.runtime.version);
  const runtime = [];
  for (const file of manifest.runtime.files) {
    if (!(await cache.match(manifest.runtime.base + file.name))) runtime.push(file);
  }
  const need = transfer(manifest, missing) + runtime.reduce((sum, file) => sum + file.size, 0);
  const info = Object.assign(summary(before), { need, total: manifest.download, next: manifest.version,
    nextBuilt: manifest.built_at, nextBytes: manifest.bytes });
  if (message.auto) {
    const link = navigator.connection || {};
    const wifi = (link.type === "wifi" || link.type === "ethernet") && !link.saveData;
    if (need > (message.limit || 0) && !wifi) { say("update", info); return; }
  }
  if (navigator.storage.estimate) {
    const room = await navigator.storage.estimate();
    const stored = Array.from(missing).reduce((sum, sha) => sum + want.get(sha), 0)
      + runtime.reduce((sum, file) => sum + file.size, 0);
    if (room.quota && room.quota - (room.usage || 0) < stored * 1.05) {
      throw new Error("Not enough free space on this device: " + Math.ceil(stored / 1e6) + " MB needed.");
    }
  }

  let done = 0, last = 0;
  const progress = force => {
    if (!force && Date.now() - last < 250) return;
    last = Date.now();
    say("downloading", Object.assign({}, info, { done: Math.min(done, need) }));
  };
  progress(true);
  for (const file of runtime) {
    if (stop) { say("paused", info); return; }
    const url = manifest.runtime.base + file.name;
    const response = await get(url, key);
    if (!response.ok) throw new Error(file.name + ": the server answered " + response.status + ".");
    const body = await response.arrayBuffer();
    if (body.byteLength !== file.size) throw new Error(file.name + " arrived incomplete.");
    await cache.put(url, new Response(body, { headers: { "content-type": response.headers.get("content-type") || "application/octet-stream" } }));
    done += file.size;
    progress();
  }
  const perPiece = missing.size ? transfer(manifest, missing) / missing.size : 0;
  const queue = Array.from(missing);
  let gone = false;                      // a piece the server no longer has: its manifest moved on
  async function worker() {
    while (queue.length && !stop && !gone) {
      const sha = queue.pop();
      let buffer = null;
      for (let tries = 0; tries < 4 && !buffer && !stop; tries += 1) {
        try {
          const response = await get("/offline/chunk/" + sha, key);
          if (response.status === 404) { gone = true; return; }
          if (!response.ok) throw new Error("status " + response.status);
          const body = await response.arrayBuffer();
          if (body.byteLength !== want.get(sha) || (await hex(body)) !== sha) throw new Error("a piece arrived damaged");
          buffer = body;
        } catch (error) {
          if (tries === 3) throw error;
          await new Promise(resolve => setTimeout(resolve, 800 * (tries + 1)));
        }
      }
      if (!buffer) return;
      await store(dir, sha, buffer);
      done += perPiece;
      progress();
    }
  }
  await Promise.all(Array.from({ length: AT_ONCE }, worker));
  if (stop) { say("paused", info); return; }
  if (gone) {
    if (message.again) throw new Error("The copy changed during the download. Try again.");
    return run(Object.assign({}, message, { again: true }));
  }
  await record(manifest);
  await tidy(manifest);
  await photos(manifest);                // the copy works from here on; the photos follow
}

// Delete pieces and runtimes the current copy does not use, unless an engine is
// running (it may still be reading the previous copy's pieces).
async function tidy(manifest) {
  const clean = async () => {
    const want = pieces(manifest);
    const dir = await folder(true);
    const old = [];
    for await (const name of dir.keys()) if (!want.has(name)) old.push(name);
    for (const name of old) await dir.removeEntry(name).catch(() => undefined);
    for (const name of await caches.keys()) {
      if (name.startsWith(RUNTIME) && name !== RUNTIME + manifest.runtime.version) await caches.delete(name);
    }
  };
  if (!navigator.locks) return clean();
  return navigator.locks.request("offline-engine", { ifAvailable: true }, lock => (lock ? clean() : undefined));
}

async function remove() {
  const clear = async () => {
    await (await caches.open(META)).delete(ACTIVE);
    const root = await navigator.storage.getDirectory();
    await root.removeEntry("offline", { recursive: true }).catch(() => undefined);
    for (const name of await caches.keys()) if (name.startsWith(RUNTIME) || name === PHOTOS) await caches.delete(name);
    await (await caches.open(META)).delete(RETRY);
    say("none");
  };
  if (!navigator.locks) return clear();
  return navigator.locks.request("offline-engine", { ifAvailable: true }, lock => {
    if (!lock) { say("error", { error: "The offline copy is in use in another window. Close it and try again." }); return undefined; }
    return clear();
  });
}
