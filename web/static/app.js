// Shared page behavior: sortable tables, filters, search. No dependencies.
(function () {
  "use strict";

  function setParam(name, value) {
    var url = new URL(window.location.href);
    if (value === "" || value == null) url.searchParams.delete(name);
    else url.searchParams.set(name, value);
    return url;
  }

  // <select data-nav="season"> and <input type=date data-nav="date"> change the URL.
  document.querySelectorAll("[data-nav]").forEach(function (control) {
    var before = control.value;
    control.addEventListener("change", function () {
      var value = control.value;
      if (value === "__custom") {   // "Other number..." in a minimum menu
        var picked = control.selectedOptions[0];
        var typed = window.prompt((picked && picked.dataset.prompt) || "Minimum", "");
        var n = typed == null ? NaN : parseFloat(String(typed).replace(/,/g, ""));
        if (isNaN(n) || n < 0) { control.value = before; return; }
        value = String(Math.round(n));
      }
      var url = setParam(control.dataset.nav, value);
      url.searchParams.delete("page");             // a new filter starts again at page 1
      (control.dataset.drop || "").split(",").forEach(function (name) {
        if (name) url.searchParams.delete(name);
      });
      window.location.href = url.pathname + url.search.replace(/%2C/g, ",") + (control.dataset.hash || "");
    });
  });

  // Season or range (.spanpick: ?season=&to=). Season shows one menu: a pick shows that
  // season. Range shows both ends: changing one keeps the other, and only a pick past it
  // moves it along. Range on a single season shows the second menu, then either end is picked.
  document.querySelectorAll(".spanpick[data-lo]").forEach(function (box) {
    var lo = +box.dataset.lo, hi = +box.dataset.hi;
    var first = box.querySelector('select[data-end="first"]'), last = box.querySelector('select[data-end="last"]');
    function go(a, b) {
      var url = new URL(window.location.href);
      url.searchParams.set("season", a);
      if (a === b) url.searchParams.delete("to"); else url.searchParams.set("to", b);
      ["span", "page"].forEach(function (name) { url.searchParams.delete(name); });
      window.location.href = url.pathname + url.search.replace(/%2C/g, ",").replace(/%3A/g, ":");
    }
    box.querySelectorAll("[data-set]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (button.dataset.set === "one") {
          if (box.dataset.mode !== "one") go(hi, hi);          // the range's last season on its own
          return;
        }
        box.dataset.mode = "range";
        box.querySelectorAll("[data-set]").forEach(function (b) { b.classList.toggle("on", b === button); });
        last.value = String(hi);
      });
    });
    first.addEventListener("change", function () {
      var value = +first.value;
      if (box.dataset.mode === "one") go(value, value);
      else go(value, Math.max(value, hi));
    });
    last.addEventListener("change", function () {
      var value = +last.value;
      go(Math.min(lo, value), value);
    });
  });

  // <select data-append="t"> adds its value to a comma-separated parameter.
  document.querySelectorAll("select[data-append]").forEach(function (select) {
    select.addEventListener("change", function () {
      if (!select.value) return;
      var url = new URL(window.location.href);
      var have = (url.searchParams.get(select.dataset.append) || "").split(",").filter(Boolean);
      have.push(select.value);
      url.searchParams.set(select.dataset.append, have.join(","));
      window.location.href = url.pathname + url.search.replace(/%2C/g, ",");
    });
  });

  // Click a header to sort; click again to flip.
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var head = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    if (!head) return;
    Array.prototype.forEach.call(head.cells, function (cell, index) {
      if (!cell.dataset.key) return;
      cell.addEventListener("click", function () {
        var dir = cell.classList.contains("sorted")
          ? (cell.classList.contains("asc") ? "desc" : "asc")
          : (cell.dataset.dir || "desc");
        if (table.hasAttribute("data-server-sort")) {
          // More rows than one page (tables.py): the server sorts all of them.
          var url = setParam("sort", cell.dataset.key);
          url.searchParams.set("dir", dir);
          url.searchParams.delete("page");
          window.location.href = url.pathname + url.search.replace(/%2C/g, ",").replace(/%3A/g, ":");
          return;
        }
        sortTable(table, index, dir, cell.dataset.type === "text");
        Array.prototype.forEach.call(head.cells, function (other) {
          other.classList.remove("sorted", "asc");
        });
        cell.classList.add("sorted");
        if (dir === "asc") cell.classList.add("asc");
      });
    });
  });

  function sortTable(table, index, dir, text) {
    var sign = dir === "asc" ? 1 : -1;
    Array.prototype.forEach.call(table.tBodies, function (body) {
      // "child" rows (a season's per-club and league rows) move with the row above them.
      var rows = [], children = new Map(), last = null;
      Array.prototype.forEach.call(body.rows, function (row) {
        if (row.classList.contains("child")) {
          if (last) children.get(last).push(row);
        } else if (!row.classList.contains("fixed")) {
          rows.push(row); children.set(row, []); last = row;
        }
      });
      var keyed = rows.map(function (row, order) {
        var cell = row.cells[index];
        var raw = cell ? (cell.dataset.v != null ? cell.dataset.v : cell.textContent.trim()) : "";
        return { row: row, raw: raw, num: parseFloat(raw), order: order };
      });
      keyed.sort(function (a, b) {
        if (text) return sign * a.raw.localeCompare(b.raw) || a.order - b.order;
        var an = isNaN(a.num), bn = isNaN(b.num);
        if (an || bn) return an === bn ? a.order - b.order : an ? 1 : -1;  // blanks last
        return sign * (a.num - b.num) || a.order - b.order;
      });
      var fixed = Array.prototype.filter.call(body.rows, function (row) {
        return row.classList.contains("fixed");
      });
      keyed.forEach(function (item, place) {
        body.appendChild(item.row);
        children.get(item.row).forEach(function (child) { body.appendChild(child); });
        var rank = item.row.querySelector("td.rank");
        if (rank) rank.textContent = place + 1;
        Array.prototype.forEach.call(item.row.cells, function (cell, i) {
          cell.classList.toggle("sorted", i === index);
        });
      });
      fixed.forEach(function (row) { body.appendChild(row); });
    });
  }

  // <input data-filter="#players"> hides rows whose name does not match.
  document.querySelectorAll("input[data-filter]").forEach(function (input) {
    var table = document.querySelector(input.dataset.filter);
    var count = document.querySelector(input.dataset.count || "#nothing");
    if (!table) return;
    // data-find: Enter searches every page of the table on the server (?find=).
    if (input.hasAttribute("data-find")) input.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") return;
      event.preventDefault();
      var url = setParam("find", input.value.trim());
      url.searchParams.delete("page");
      window.location.href = url.pathname + url.search.replace(/%2C/g, ",").replace(/%3A/g, ":");
    });
    input.addEventListener("input", function () {
      var needle = fold(input.value);
      var shown = 0;
      var body = table.querySelector("tbody:not(.lgbody)") || table.tBodies[0];
      Array.prototype.forEach.call(body.rows, function (row) {
        var hit = !needle || fold(row.dataset.name || row.textContent).indexOf(needle) !== -1;
        row.hidden = !hit;
        if (hit) shown += 1;
      });
      if (count) count.textContent = shown;
    });
  });

  function fold(text) {
    return String(text || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  // Search boxes. data-pick="p" adds the chosen player to ?p= instead of opening him.
  document.querySelectorAll("input[data-search]").forEach(function (input) {
    var box = document.querySelector(input.dataset.search);
    if (!box) return;
    var timer = null, items = [], active = -1, last = "";

    function close() { box.hidden = true; active = -1; }

    function choose(item) {
      if (input.dataset.pick) {
        if (item.kind !== "player") return;
        var url = new URL(window.location.href);
        var have = (url.searchParams.get(input.dataset.pick) || "").split(",").filter(Boolean);
        if (have.indexOf(String(item.pid)) === -1) have.push(item.pid);
        url.searchParams.set(input.dataset.pick, have.slice(-4).join(","));
        url.searchParams.delete("t");
        window.location.href = url.pathname + url.search.replace(/%2C/g, ",");
      } else {
        window.location.href = item.url;
      }
    }

    function render() {
      box.textContent = "";
      var list = input.dataset.pick ? items.filter(function (i) { return i.kind === "player"; }) : items;
      if (!list.length) {
        var none = document.createElement("div");
        none.className = "none";
        none.textContent = "No match";
        box.appendChild(none);
      }
      list.forEach(function (item, index) {
        var link = document.createElement("a");
        link.href = item.url;
        if (index === active) link.className = "on";
        if (item.kind === "team" && item.logo) {
          var img = document.createElement("img");
          img.src = item.logo;
          img.style.objectFit = "contain";
          img.width = 20; img.height = 20; img.alt = "";
          link.appendChild(img);
        }
        var name = document.createElement("span");
        name.textContent = item.label;
        var sub = document.createElement("small");
        sub.textContent = item.sub || "";
        link.appendChild(name);
        link.appendChild(sub);
        link.addEventListener("mousedown", function (event) { event.preventDefault(); choose(item); });
        box.appendChild(link);
      });
      items = list;
      box.hidden = false;
    }

    input.addEventListener("input", function () {
      var text = input.value.trim();
      clearTimeout(timer);
      if (text.length < 2) { close(); return; }
      timer = setTimeout(function () {
        last = text;
        fetch("/api/search?q=" + encodeURIComponent(text))
          .then(function (r) { return r.json(); })
          .then(function (data) { if (last === text) { items = data; active = -1; render(); } })
          .catch(close);
      }, 140);
    });
    input.addEventListener("keydown", function (event) {
      if (box.hidden) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        active = (active + (event.key === "ArrowDown" ? 1 : -1) + items.length) % Math.max(items.length, 1);
        render();
      } else if (event.key === "Enter") {
        event.preventDefault();
        var pick = items[active < 0 ? 0 : active];
        if (pick) choose(pick);
      } else if (event.key === "Escape") {
        close();
      }
    });
    input.addEventListener("blur", function () { setTimeout(close, 120); });
  });

  // Players and Teams: stat ranges (?f=HR:30:,K%::20), as on basketball.asir.dev. The server filters the table; this
  // opens the form (a chip opens its own range) and writes the parameter.
  var ranges = document.getElementById("statfilter");
  if (ranges) {
    var form = ranges.querySelector(".sf-form"), add = ranges.querySelector(".sf-add");
    var stat = form.querySelector("select"), lo = form.querySelector('[name="lo"]'), hi = form.querySelector('[name="hi"]');
    var hintLine = form.querySelector(".sf-hint"), editing = "";
    var parts = (ranges.dataset.filters || "").split(",").filter(Boolean).map(function (part) {
      var bits = part.split(":");
      return { key: bits[0], lo: bits[1], hi: bits[2], part: part };
    });
    var HINTS = {
      pct1: "In percent, as the table shows it: 24.3 means 24.3%.",
      avg: "As the table shows it: .300.",
      p3: "As the table shows it: .550.",
      ip: "Innings as box scores write them: 150.1 is 150\u2153, 150.2 is 150\u2154.",
      s1: "Negative numbers work: -2 for a minus.",
      s0: "Negative numbers work: -2 for a minus.",
    };
    var hint = function () {
      var option = stat.options[stat.selectedIndex];
      hintLine.textContent = HINTS[option && option.dataset.fmt] || "";
    };
    var openForm = function (key, low, high) {
      editing = key;
      stat.value = key;
      if (stat.selectedIndex < 0) stat.selectedIndex = 0;
      stat.dispatchEvent(new Event("change"));
      lo.value = low || "";
      hi.value = high || "";
      form.hidden = false;
      add.hidden = true;
      hint();
      if (window.matchMedia("(pointer: fine)").matches) lo.focus();
    };
    add.addEventListener("click", function () { openForm(ranges.dataset.default, "", ""); });
    ranges.querySelectorAll("[data-edit]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var found = parts.filter(function (p) { return p.key === chip.dataset.edit; })[0];
        if (found) openForm(found.key, found.lo, found.hi);
      });
    });
    form.querySelector("[data-cancel]").addEventListener("click", function () {
      form.hidden = true;
      add.hidden = false;
      editing = "";
    });
    stat.addEventListener("change", hint);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var low = lo.value.trim(), high = hi.value.trim();
      if ((low === "" && high === "") || !lo.checkValidity() || !hi.checkValidity()) {
        hintLine.textContent = "Type a number in At least, At most or both.";
        return;
      }
      var keep = parts.filter(function (p) { return p.key !== stat.value && p.key !== editing; })
        .map(function (p) { return p.part; });
      keep.push(stat.value + ":" + low + ":" + high);
      var url = setParam("f", keep.join(","));
      window.location.href = url.pathname + url.search.replace(/%2C/g, ",").replace(/%3A/g, ":");
    });
  }

  // "/" focuses the main search.
  document.addEventListener("keydown", function (event) {
    var main = document.getElementById("search");
    if (event.key === "/" && main && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
      event.preventDefault();
      main.focus();
    }
  });

  // Player pages: tap one season, then another, to see that span (?from=&to=).
  var bar = document.getElementById("spanbar");
  var years = document.querySelectorAll("button.yr");
  if (bar && years.length) {
    var picked = null;
    var clear = function () {
      picked = null;
      bar.hidden = true;
      years.forEach(function (b) { b.closest("tr").classList.remove("pick"); });
    };
    bar.querySelector("button").addEventListener("click", clear);
    years.forEach(function (button) {
      button.addEventListener("click", function () {
        var season = +button.dataset.season;
        if (picked === null) {
          picked = season;
          years.forEach(function (b) { b.closest("tr").classList.toggle("pick", +b.dataset.season === season); });
          bar.querySelector("span").textContent = season + " picked. Tap another season for the span, or " + season + " again for that season alone.";
          bar.hidden = false;
          return;
        }
        var url = new URL(window.location.href);
        url.searchParams.set("from", Math.min(picked, season));
        url.searchParams.set("to", Math.max(picked, season));
        url.searchParams.delete("pseason");
        var section = button.closest("section");
        url.hash = section && section.id ? section.id : "";
        window.location.href = url.toString();
      });
    });
  }

  // Player pages: "League average under every season" (remembered on this device).
  var toggles = document.querySelectorAll("input[data-lgtoggle]");
  if (toggles.length) {
    var saved = false;
    try { saved = window.localStorage.getItem("lgEvery") === "1"; } catch (e) { /* private mode */ }
    var apply = function (on) {
      document.querySelectorAll("table.lgtable").forEach(function (t) { t.classList.toggle("lg-every", on); });
      toggles.forEach(function (box) { box.checked = on; });
    };
    apply(saved);
    toggles.forEach(function (box) {
      box.addEventListener("change", function () {
        apply(box.checked);
        try { window.localStorage.setItem("lgEvery", box.checked ? "1" : "0"); } catch (e) { /* ignore */ }
      });
    });
  }

  // Pin the header cell above a pinned (sticky) name column too, so the headings
  // stay in line with the cells when a wide table scrolls sideways.
  document.querySelectorAll("table.stats").forEach(function (table) {
    var cell = table.querySelector("tbody td.name");
    if (!cell || !table.tHead) return;
    var index = 0;
    for (var i = 0; i < cell.cellIndex; i++) index += cell.parentNode.cells[i].colSpan || 1;
    Array.prototype.forEach.call(table.tHead.rows, function (row) {
      var at = 0;
      Array.prototype.some.call(row.cells, function (th) {
        if (at === index) { th.classList.add("name"); return true; }
        at += th.colSpan || 1;
        return at > index;
      });
    });
  });
})();

// Home-screen app and offline use (web/sw.js). A page served from the offline copy
// has data-saved on <html>; say so at the top. In the installed app, coming back after
// 15+ minutes reloads the page so scores and standings are current.
(function () {
  "use strict";
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").then(function () {
      return navigator.serviceWorker.ready;
    }).then(function (registration) {
      if (navigator.onLine && registration.active) registration.active.postMessage("warm");
    }).catch(function () { /* signed out or private mode: the site still works online */ });
  }
  var standalone = window.matchMedia && window.matchMedia("(display-mode: standalone)").matches;
  if (standalone && navigator.storage && navigator.storage.persist) {
    navigator.storage.persisted().then(function (yes) { if (!yes) navigator.storage.persist(); })
      .catch(function () {});
  }

  // data-saved: a copy of this page saved from the server. data-local: the page as the
  // full offline copy on this device renders it (web/offline.py), with that copy's data time.
  var saved = document.documentElement.getAttribute("data-saved");
  var local = document.documentElement.getAttribute("data-local");
  var main = document.querySelector("main.page");
  if ((saved || local != null) && main) {
    var when = new Date(saved || local), note = document.createElement("div"), again = document.createElement("a");
    var stamp = isNaN(when) ? "earlier" : when.toLocaleString([], {
      weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"
    });
    note.className = "note offline-note";
    note.setAttribute("role", "status");
    note.textContent = (saved ? "Offline: saved copy from " + stamp : "Offline copy: data as of " + stamp) + ". ";
    again.href = window.location.href;
    again.target = "_top";          // out of the offline shell's frame, back to the server
    again.textContent = navigator.onLine ? "Try again" : "Reload when back online";
    note.appendChild(again);
    main.insertBefore(note, main.firstChild);
    window.addEventListener("online", function () { again.textContent = "Back online: reload"; });
  }

  if (standalone) {
    var hiddenAt = 0;
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { hiddenAt = Date.now(); return; }
      if (hiddenAt && Date.now() - hiddenAt > 15 * 60 * 1000 && navigator.onLine) window.location.reload();
    });
  }
})();
