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

  console.log("service worker tests passed");
})().catch(error => {
  console.error(error);
  process.exit(1);
});
