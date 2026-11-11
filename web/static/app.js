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
      (control.dataset.drop || "").split(",").forEach(function (name) {
        if (name) url.searchParams.delete(name);
      });
      window.location.href = url.pathname + url.search.replace(/%2C/g, ",") + (control.dataset.hash || "");
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
      var rows = Array.prototype.filter.call(body.rows, function (row) {
        return !row.classList.contains("fixed");
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
    input.addEventListener("input", function () {
      var needle = fold(input.value);
      var shown = 0;
      Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
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

  // "/" focuses the main search.
  document.addEventListener("keydown", function (event) {
    var main = document.getElementById("search");
    if (event.key === "/" && main && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
      event.preventDefault();
      main.focus();
    }
  });
})();
