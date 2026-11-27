// Run with: node tests/test_sw.js [path/to/sw.js]
// The service worker must answer sign-in navigations (/oauth2/) with the navigation
// preload response. Passing them through sends /oauth2/callback a second time, which
// replays its one-time code: the gateway then shows a 500 or 403 page after a good
// sign-in (seen on Chrome for Android, 2026-11-16).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const file = process.argv[2] || path.join(__dirname, "..", "web", "sw.js");
const source = fs.readFileSync(file, "utf8");

async function dispatch(url, mode, preloadResponse) {
  const listeners = {};
  const sent = [];
  const sandbox = {
    CONFIG: { static: [], pages: ["/"], imageHosts: [], imagePaths: [], dataPaths: [], site: "Test", css: "/x.css" },
    self: { location: { origin: "https://site.test" }, addEventListener: (type, fn) => { listeners[type] = fn; } },
    fetch: async request => { sent.push(request); return "network"; },
    URL, Promise, setTimeout, clearTimeout,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  let answer;
  listeners.fetch({
    request: { method: "GET", url, mode },
    preloadResponse,
    respondWith: value => { answer = value; },
    waitUntil: () => {},
  });
  return { answered: answer !== undefined, response: await answer, sent: sent.length };
}

(async () => {
  const callback = "https://site.test/oauth2/callback?code=c&state=s";
  let r = await dispatch(callback, "navigate", Promise.resolve("preloaded"));
  assert.equal(r.answered, true, "the worker answers a sign-in navigation");
  assert.equal(r.response, "preloaded", "with the navigation preload response");
  assert.equal(r.sent, 0, "and does not send the callback a second time");

  r = await dispatch(callback, "navigate", Promise.resolve(undefined));
  assert.deepEqual([r.response, r.sent], ["network", 1], "without a preload it is sent exactly once");

  r = await dispatch(callback, "navigate", Promise.reject(new Error("preload failed")));
  assert.deepEqual([r.response, r.sent], ["network", 1], "a failed preload falls back to one request");

  r = await dispatch("https://site.test/oauth2/auth", "cors", undefined);
  assert.deepEqual([r.answered, r.sent], [false, 0], "non-navigation sign-in requests still pass straight through");

  // Navigation preload: on, except in Firefox, where a failed preload fails the navigation
  // before the worker's saved page can be used (found with tools/offline_browser.py).
  const chrome = "Mozilla/5.0 (Linux; Android 16; Pixel) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0 Mobile Safari/537.36";
  const safari = "Mozilla/5.0 (iPad; CPU OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Mobile/15E148 Safari/604.1";
  const firefox = "Mozilla/5.0 (Android 16; Mobile; rv:146.0) Gecko/146.0 Firefox/146.0";
  assert.deepEqual(await activate(chrome), ["enable"]);
  assert.deepEqual(await activate(safari), ["enable"]);
  assert.deepEqual(await activate(firefox), ["disable"], "Firefox: navigation preload is switched off");

  await offlineCopyTests();
  console.log("service worker tests passed");
  process.exit(0);          // message ports opened by the worker would keep Node alive
})().catch(error => {
  console.error(error);
  process.exit(1);
});

// Run the worker's activate step under a browser's user agent; returns what it did to navigation preload.
async function activate(userAgent) {
  const listeners = {}, calls = [];
  const sandbox = {
    CONFIG: { static: [], pages: ["/"], imageHosts: [], imagePaths: [], dataPaths: [], site: "Test", css: "/x.css", offline: null },
    self: {
      location: { origin: "https://site.test" }, navigator: { userAgent },
      addEventListener: (type, fn) => { listeners[type] = fn; },
      registration: { navigationPreload: { enable: async () => { calls.push("enable"); }, disable: async () => { calls.push("disable"); } } },
      clients: { claim: async () => {} },
    },
    caches: fakeCaches(), URL, Promise, setTimeout, clearTimeout, Set,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  let done;
  listeners.activate({ waitUntil: promise => { done = promise; } });
  await done;
  return calls;
}

// ------------------------------------------------------------------ the full offline copy
// A device that downloaded the copy (web/offline.py) has a record in the meta cache.
// With no connection a top-level page is the shell; a page in the shell's frame is
// rendered by the shell's worker, unless a copy saved from the server is newer.

function fakeCaches() {
  const stores = new Map();
  const full = key => new URL(typeof key === "string" ? key : key.url, "https://site.test").href;
  const open = async name => {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name);
    return {
      match: async key => (store.has(full(key)) ? store.get(full(key)).clone() : undefined),
      put: async (key, response) => { store.set(full(key), response); },
      delete: async key => store.delete(full(key)),
      keys: async () => Array.from(store.keys()).map(url => ({ url })),
    };
  };
  return { open, keys: async () => Array.from(stores.keys()), delete: async name => stores.delete(name) };
}

function world({ online, shellAnswer, server }) {
  const listeners = {}, sent = [], asked = [];
  const caches = fakeCaches();
  const shell = {
    id: "shell-1", frameType: "top-level",
    postMessage(message, ports) {
      asked.push(message);
      if (message.type === "offline-shell?") ports[0].postMessage({ shell: true });
      else ports[0].postMessage(shellAnswer(message));
    },
  };
  const plain = { id: "page-1", frameType: "top-level", postMessage(message, ports) { ports[0].postMessage({ shell: false }); } };
  const sandbox = {
    CONFIG: { static: [], pages: ["/"], imageHosts: [], imagePaths: ["/logos/"], dataPaths: ["/api/chart"], site: "Test",
      css: "/x.css", offline: { shell: "/static/offline/shell.js?v=1", engine: "/static/offline/engine.js?v=1" } },
    self: {
      location: { origin: "https://site.test" }, navigator: { onLine: online },
      addEventListener: (type, fn) => { listeners[type] = fn; },
      clients: { get: async id => (id === shell.id ? shell : undefined), matchAll: async () => [plain, shell] },
    },
    fetch: async request => { sent.push(request); if (!online) throw new TypeError("offline"); return server ? server(request) : new Response("from the server", { headers: { "content-type": "text/html" } }); },
    caches, URL, Promise, setTimeout, clearTimeout, Response, Headers, MessageChannel, TextDecoder, Date, console,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  async function request(url, more) {
    let answer;
    const pending = [];
    listeners.fetch({
      request: Object.assign({ method: "GET", url, mode: "navigate", destination: "document" }, more),
      preloadResponse: Promise.resolve(undefined),
      respondWith: value => { answer = value; },
      waitUntil: promise => { pending.push(Promise.resolve(promise).catch(() => undefined)); },
    });
    const response = await answer;
    await Promise.all(pending);
    return response;
  }
  return { caches, request, sent, asked, sandbox };
}

const html = text => ({ status: 200, headers: [["Content-Type", "text/html; charset=utf-8"], ["Content-Length", "1"]],
  body: new TextEncoder().encode(text).buffer });

async function holdCopy(caches, checked) {
  await (await caches.open("meta-v1")).put("/__offline/manifest", new Response(
    JSON.stringify({ version: "v1", built_at: "2026-11-22T15:00:00Z" }), { headers: { "x-checked": checked } }));
}

async function offlineCopyTests() {
  // No copy on the device: unchanged behaviour (the list of saved pages).
  let w = world({ online: false });
  let r = await w.request("https://site.test/player/7");
  assert.match(await r.text(), /You're offline/, "without a copy an unsaved page is still the offline list");

  // With a copy, a top-level page with no connection is the shell.
  w = world({ online: false });
  await holdCopy(w.caches, "2026-11-22T16:00:00Z");
  r = await w.request("https://site.test/player/7?x=1");
  let body = await r.text();
  assert.match(body, /<iframe id="view"/, "with a copy the page opens in the shell");
  assert.match(body, /src="\/static\/offline\/shell\.js\?v=1" data-engine="\/static\/offline\/engine\.js\?v=1"/);

  // In the shell's frame the page comes from the shell's worker, marked with the copy's data time.
  w = world({ online: false, shellAnswer: () => html('<!doctype html><html lang="en"><body>on the device</body></html>') });
  await holdCopy(w.caches, "2026-11-22T16:00:00Z");
  r = await w.request("https://site.test/player/7?x=1", { destination: "iframe" });
  body = await r.text();
  assert.match(body, /on the device/);
  assert.match(body, /<html data-local="2026-11-22T15:00:00Z" lang="en">/, "the page carries the copy's data time");
  assert.equal(r.headers.get("content-length"), null, "the device's length header is dropped (the body was changed)");
  assert.deepEqual(w.asked.map(m => m.type), ["offline-shell?", "offline-request"]);
  assert.equal(w.asked[1].url, "https://site.test/player/7?x=1");
  assert.equal(w.sent.length, 0, "and the server is not asked while offline");

  // A redirect from the device is a redirect for the frame.
  w = world({ online: false, shellAnswer: () => ({ status: 301, headers: [["Location", "/chart?view=team"]], body: new ArrayBuffer(0) }) });
  await holdCopy(w.caches, "2026-11-22T16:00:00Z");
  r = await w.request("https://site.test/?view=team", { destination: "iframe" });
  assert.deepEqual([r.status, r.headers.get("location")], [301, "https://site.test/chart?view=team"]);

  // A page saved from the server after the copy was last confirmed current wins...
  const saved = when => new Response('<html lang="en">saved</html>', { headers: { "content-type": "text/html", "x-saved": when } });
  w = world({ online: false, shellAnswer: () => html('<html lang="en">on the device</html>') });
  await holdCopy(w.caches, "2026-11-22T16:00:00Z");
  await (await w.caches.open("pages-v1")).put("https://site.test/scores", saved("2026-11-22T17:00:00.000Z"));
  r = await w.request("https://site.test/scores", { destination: "iframe" });
  assert.match(await r.text(), /<html data-saved="2026-11-22T17:00:00.000Z" lang="en">saved/, "a newer saved page is preferred");
  // ...and an older one does not.
  await (await w.caches.open("pages-v1")).put("https://site.test/scores", saved("2026-11-22T15:30:00.000Z"));
  r = await w.request("https://site.test/scores", { destination: "iframe" });
  assert.match(await r.text(), /on the device/, "an older saved page gives way to the copy");

  // The shell's worker failed (status 0): fall back to the saved page.
  w = world({ online: false, shellAnswer: () => ({ status: 0 }) });
  await holdCopy(w.caches, "2026-11-22T16:00:00Z");
  await (await w.caches.open("pages-v1")).put("https://site.test/scores", saved("2026-11-22T15:30:00.000Z"));
  r = await w.request("https://site.test/scores", { destination: "iframe" });
  assert.match(await r.text(), /saved/, "a failed engine falls back to the saved page");

  // Online, a framed page still comes from the server.
  w = world({ online: true, shellAnswer: () => html("<html>on the device</html>") });
  await holdCopy(w.caches, "2026-11-22T16:00:00Z");
  r = await w.request("https://site.test/scores", { destination: "iframe" });
  assert.equal(await r.text(), "from the server");

  // Online, the server sends the frame to sign in (the gateway's 302 to id.asir.dev, which
  // refuses frames). The frame does not follow it: its page sends the whole window to the
  // address, and the shell's worker is not asked (2026-11-27: the shell spun for ever).
  w = world({ online: true, shellAnswer: () => html("<html>on the device</html>"),
    server: () => new Response(null, { status: 302, headers: { location: "https://id.test/authorize" } }) });
  await holdCopy(w.caches, "2026-11-22T16:00:00Z");
  r = await w.request("https://site.test/players?mode=pergame", { destination: "iframe" });
  body = await r.text();
  assert.equal(r.status, 200);
  assert.match(body, /top\.location\.replace\("https:\/\/site\.test\/players\?mode=pergame"\)/, "the window goes to the page itself");
  assert.equal(w.asked.length, 0, "the device is not asked");
  // The window's own request that follows waits for the server, even if the browser
  // briefly reports no connection, instead of opening the shell again.
  w.sandbox.self.navigator.onLine = false;
  r = await w.request("https://site.test/players?mode=pergame");
  assert.equal(r.status, 302, "the top-level page gets the server's sign-in redirect");
  assert.equal(r.headers.get("location"), "https://id.test/authorize");

  // Search and chart data fall back to the device when the server cannot be reached.
  const data = () => ({ status: 200, headers: [["Content-Type", "application/json"]], body: new TextEncoder().encode('[{"label":"device"}]').buffer });
  w = world({ online: false, shellAnswer: data });
  await holdCopy(w.caches, "2026-11-22T16:00:00Z");
  r = await w.request("https://site.test/api/search?q=ruth", { mode: "cors", destination: "" });
  assert.equal(await r.text(), '[{"label":"device"}]', "search asks the device");
  r = await w.request("https://site.test/api/chart?view=team", { mode: "cors", destination: "" });
  assert.equal(await r.text(), '[{"label":"device"}]', "chart data asks the device");

  // This season's player photos (kept by the copy in their own cache) are served without the network.
  w = world({ online: false });
  w.sandbox.CONFIG.imageHosts = ["img.test"];
  await (await w.caches.open("photos-v1")).put("https://img.test/people/7/headshot", new Response("photo"));
  r = await w.request("https://img.test/people/7/headshot", { mode: "no-cors", destination: "image" });
  assert.equal(await r.text(), "photo", "a photo the copy holds is served from its cache");
  assert.equal(w.sent.length, 0);

  // Python's files come from the cache the downloader filled.
  w = world({ online: false });
  await (await w.caches.open("offline-rt-314.0.8")).put("https://site.test/offline/rt/314.0.8/pyodide.mjs", new Response("export {}"));
  r = await w.request("https://site.test/offline/rt/314.0.8/pyodide.mjs", { mode: "cors", destination: "script" });
  assert.equal(await r.text(), "export {}");

  // The manifest and the pieces are never answered by the worker.
  w = world({ online: true });
  r = await w.request("https://site.test/offline/manifest.json", { mode: "cors", destination: "" });
  assert.equal(r, undefined, "the manifest request passes straight to the network");
}
