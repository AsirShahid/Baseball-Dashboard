// The offline copy's shell: the page web/sw.js shows when there is no connection and
// this device holds an offline copy.
//
// It starts the engine (engine.js, a worker running the site's own code) once and keeps
// it for as long as the app stays open. The site itself runs in a frame below: every
// page the frame opens is a request the service worker passes here, and the engine's
// answer goes back as the page. So links, filters, search and charts work as they do
// online, and only the first page waits for Python to start.
// The same file runs on basketball.asir.dev and baseball.asir.dev.
(function () {
  "use strict";
  var script = document.currentScript;
  var view = document.getElementById("view");
  var boot = document.getElementById("boot");
  var step = document.getElementById("boot-step");
  var worker = new Worker(script.dataset.engine, { type: "module" });
  var waiting = new Map();
  var count = 0;
  var dead = false;

  worker.onmessage = function (event) {
    var message = event.data || {};
    if (message.type === "progress") {
      step.textContent = message.text + "...";
    } else if (message.type === "failed") {
      step.textContent = message.error;
      boot.classList.add("failed");
    } else if (message.type === "response") {
      var reply = waiting.get(message.id);
      waiting.delete(message.id);
      if (reply) reply(message);
    }
  };
  worker.onerror = function (event) {
    step.textContent = "The offline copy could not start" + (event && event.message ? ": " + event.message : ".");
    boot.classList.add("failed");
    dead = true;                    // status 0: web/sw.js falls back to the saved pages
    waiting.forEach(function (reply) { reply({ status: 0 }); });
    waiting.clear();
  };

  // web/sw.js asks every open window whether it is the shell, then sends it requests.
  navigator.serviceWorker.addEventListener("message", function (event) {
    var message = event.data || {}, port = event.ports && event.ports[0];
    if (!port) return;
    if (message.type === "offline-shell?") {
      port.postMessage({ shell: true });
    } else if (message.type === "offline-request") {
      if (dead) { port.postMessage({ status: 0 }); return; }
      var id = ++count;
      waiting.set(id, function (answer) {
        port.postMessage({ status: answer.status, headers: answer.headers, body: answer.body },
          answer.body ? [answer.body] : []);
      });
      worker.postMessage({ type: "request", id: id, method: message.method, url: message.url });
    }
  });
  if (navigator.serviceWorker.startMessages) navigator.serviceWorker.startMessages();

  // Keep this window's address and title on the page the frame shows, so a reload,
  // a share and the app switcher all name that page.
  function follow() {
    var doc, at;
    try {
      doc = view.contentDocument;
      at = view.contentWindow.location;
      if (!doc || at.href === "about:blank") return;
    } catch (error) {
      return;                       // another site's page: nothing to read
    }
    boot.hidden = true;
    if (doc.title) document.title = doc.title;
    var here = at.pathname + at.search + at.hash;
    if (here !== location.pathname + location.search + location.hash) history.replaceState(null, "", here);
    // A link to another site leaves the app, as it does from the installed app online.
    doc.addEventListener("click", function (event) {
      var link = event.target && event.target.closest && event.target.closest("a[href]");
      if (link && link.origin !== location.origin && !link.target) link.target = "_blank";
    }, true);
  }
  view.addEventListener("load", follow);
  view.src = location.pathname + location.search + location.hash;
})();
