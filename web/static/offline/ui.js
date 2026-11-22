// The offline copy on the page: the card on About (download, update, remove) and a
// quiet check on every page that keeps the copy current.
//
// sync.js (a worker) does the work and reports states: none, locked, checking, preparing,
// downloading, paused, update, ready, busy, unable, error. A download that was started carries
// on from any page until it is complete. Updates under AUTO bytes download by
// themselves, as does any update on a connection the browser reports as Wi-Fi; a
// larger one waits for a tap on About.
// The same file runs on basketball.asir.dev and baseball.asir.dev.
(function () {
  "use strict";
  var script = document.currentScript;
  var AUTO = 40 * 1000 * 1000;
  var EVERY = 20 * 60 * 1000;

  // web/sw.js asks every window whether it is the offline shell (shell.js). This one is not.
  if (navigator.serviceWorker) {
    navigator.serviceWorker.addEventListener("message", function (event) {
      var port = event.ports && event.ports[0];
      if (port && event.data && event.data.type === "offline-shell?") port.postMessage({ shell: false });
    });
  }

  var card = document.getElementById("offline-card");
  var access = card ? card.dataset.access : "";
  var able = !!(window.Worker && window.caches && navigator.storage && navigator.storage.getDirectory
    && window.WebAssembly && navigator.serviceWorker);
  var store = {
    get: function (name) { try { return window.localStorage.getItem("offline." + name); } catch (e) { return null; } },
    set: function (name, value) {
      try {
        if (value == null) window.localStorage.removeItem("offline." + name);
        else window.localStorage.setItem("offline." + name, value);
      } catch (e) { /* private mode */ }
    },
  };

  // ?offline_key=... on any address stores the owner's key on this device.
  var here = new URL(window.location.href);
  if (here.searchParams.has("offline_key")) {
    store.set("key", here.searchParams.get("offline_key"));
    here.searchParams.delete("offline_key");
    window.history.replaceState(null, "", here.pathname + here.search + here.hash);
  }

  var framed = window.top !== window;          // inside the offline shell: the copy is in use
  // Where the copy needs a key (a public site), the card is for devices that were given
  // it: other visitors see nothing.
  var stranger = access === "key" && !store.get("key");
  if (!able) {
    if (card && access !== "local" && !stranger) {
      card.hidden = false;
      card.innerHTML = "<h2>Offline copy</h2><p class=\"sub\">This browser cannot hold the offline copy.</p>";
    }
    return;
  }

  var worker = null, listener = null;
  function run(message, onState) {
    if (!worker) {
      worker = new Worker(new URL("sync.js" + new URL(script.src).search, script.src).href);
      worker.onmessage = function (event) { if (listener && event.data && event.data.type === "state") listener(event.data); };
    }
    listener = onState;
    worker.postMessage(Object.assign({ key: store.get("key") || "" }, message));
  }

  function remember(state) {
    // "ready" with photos still arriving is not finished: another page carries on with them.
    if (state.state === "none" || (state.state === "ready" && !(state.photos && state.photos.busy))) {
      store.set("want", null); store.set("update", null);
    }
    if (state.state === "update") store.set("update", JSON.stringify({ need: state.need, built: state.nextBuilt }));
  }

  function mb(bytes) {
    var n = bytes / 1e6;
    return (n >= 10 ? Math.round(n) : Math.round(n * 10) / 10) + " MB";
  }

  function when(iso) {
    var date = new Date(iso);
    return isNaN(date) ? "earlier" : date.toLocaleString([], { weekday: "short", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit" });
  }

  if (!card) {
    // Any other page: carry on a download that was started, or look for an update now and then.
    if (framed || !navigator.onLine) return;
    window.caches.open("meta-v1").then(function (cache) { return cache.match("/__offline/manifest"); }).then(function (have) {
      var want = store.get("want") === "1";
      if (!have && !want) return;
      if (have && !want && Date.now() - Number(store.get("checked") || 0) < EVERY) return;
      window.setTimeout(function () {
        store.set("checked", String(Date.now()));
        run({ cmd: "sync", auto: !want, limit: AUTO }, remember);
      }, 4000);
    }).catch(function () {});
    return;
  }

  // ---------------------------------------------------------------- the card on About
  card.hidden = false;
  var title = document.createElement("h2"), text = document.createElement("p"), bar = document.createElement("progress");
  var buttons = document.createElement("div"), form = document.createElement("form");
  title.textContent = "Offline copy";
  text.className = "sub";
  bar.hidden = true; bar.max = 1;
  buttons.className = "offline-actions";
  form.hidden = true; form.className = "offline-actions";
  form.innerHTML = "<input type=\"password\" name=\"offline-key\" autocomplete=\"current-password\" placeholder=\"Key\" aria-label=\"Offline copy key\"><button type=\"submit\">Unlock</button>";
  card.append(title, text, bar, buttons, form);
  if (card.dataset.note) {                    // what this site's copy cannot do, set in about.html
    var note = document.createElement("p");
    note.className = "sub offline-limit";
    note.textContent = card.dataset.note;
    card.appendChild(note);
  }
  if (stranger) {
    // A visitor without the key sees one quiet line. The owner opens it to enter the key:
    // an installed home-screen app has no address bar for the ?offline_key= link.
    var parts = Array.prototype.slice.call(card.children), opener = document.createElement("button");
    parts.forEach(function (part) { part.style.display = "none"; });
    opener.type = "button"; opener.className = "offline-open"; opener.textContent = "Offline copy";
    card.classList.add("quiet");
    card.appendChild(opener);
    opener.addEventListener("click", function () {
      opener.remove();
      card.classList.remove("quiet");
      parts.forEach(function (part) { part.style.display = ""; });
      show({ state: "locked" });
      form.elements[0].focus();
    });
  }

  function button(label, action, plain) {
    var b = document.createElement("button");
    b.type = "button"; b.textContent = label;
    if (plain) b.className = "plain";
    b.addEventListener("click", action);
    buttons.appendChild(b);
  }

  function download() {
    store.set("want", "1");
    if (navigator.storage.persist) navigator.storage.persist().catch(function () {});
    run({ cmd: "sync" }, show);
  }

  function show(state) {
    remember(state);
    buttons.textContent = "";
    bar.hidden = true; form.hidden = true;
    var pending = null;
    try { pending = JSON.parse(store.get("update") || "null"); } catch (e) { pending = null; }
    switch (state.state) {
      case "none":
        text.textContent = "Keep the whole site on this device. Every page, tab and filter then works with no connection"
          + (state.total ? ". The download is " + mb(state.total)
            + (state.photoBytes ? ", plus about " + mb(state.photoBytes) + " of this season's player photos." : ".") : ".");
        if (navigator.onLine) button("Download", download);
        break;
      case "locked":
        if (access === "key") {
          text.textContent = store.get("key") ? "That key was not accepted. Enter the current one to unlock the offline copy on this device."
            : "Enter the key to unlock the offline copy on this device.";
          form.hidden = false;
        } else {
          text.textContent = "The offline copy is not available right now.";
        }
        break;
      case "unable":
        text.textContent = "This window cannot store files, so it cannot hold the offline copy. A private window cannot; open the site in a normal window or from the home screen.";
        break;
      case "checking":
        text.textContent = "Checking...";
        break;
      case "preparing":
        text.textContent = "The server is preparing the copy. This takes under a minute.";
        break;
      case "downloading":
        text.textContent = "Downloading: " + mb(state.done || 0) + " of " + mb(state.need) + ". You can leave this page; it carries on while the site is open.";
        bar.hidden = false; bar.value = state.need ? (state.done || 0) / state.need : 0;
        button("Pause", function () { store.set("want", null); worker.postMessage({ cmd: "stop" }); }, true);
        break;
      case "paused":
        text.textContent = "Paused. What has arrived is kept.";
        button("Resume", download);
        break;
      case "busy":
        text.textContent = "Another window of this site is downloading the copy.";
        break;
      case "update":
        text.textContent = "On this device: data as of " + when(state.built) + ". A newer copy (" + when(state.nextBuilt)
          + ") is a " + mb(state.need) + " download.";
        button("Update", download);
        button("Remove", remove, true);
        break;
      case "ready":
        var shots = state.photos, count = shots ? shots.total.toLocaleString() : "";
        text.textContent = "On this device: data as of " + when(state.built) + ", " + mb(state.bytes)
          + (shots && shots.have >= shots.total ? ", and this season's " + count + " player photos" : "")
          + ". With no connection the site opens from this copy."
          + (shots && shots.have < shots.total ? " Player photos: " + shots.have.toLocaleString() + " of " + count
            + (shots.busy ? "." : "; the rest come with the next check.") : "");
        if (shots && shots.busy) { bar.hidden = false; bar.value = shots.have / shots.total; }
        if (pending && pending.built !== state.built && navigator.onLine) button("Update (" + mb(pending.need) + ")", download);
        else if (navigator.onLine && !(shots && shots.busy)) button("Check for an update", function () { run({ cmd: "sync", auto: true, limit: AUTO }, show); }, true);
        if (!framed) button("Remove", remove, true);
        break;
      default:
        text.textContent = state.error || "Something went wrong.";
        if (navigator.onLine) button("Try again", download);
    }
  }

  function remove() {
    if (!window.confirm("Remove the offline copy from this device?")) return;
    store.set("want", null);
    run({ cmd: "remove" }, show);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    store.set("key", form.elements[0].value.trim());
    form.elements[0].value = "";
    run({ cmd: "size" }, show);
  });

  // Start: what is here, then (online) what the server has.
  if (stranger) return;
  run({ cmd: "status" }, function (state) {
    show(state);
    if (framed || !navigator.onLine) return;
    if (store.get("want") === "1") download();
    else if (state.state === "ready") run({ cmd: "sync", auto: true, limit: AUTO }, show);
    else run({ cmd: "size" }, show);
  });
})();
