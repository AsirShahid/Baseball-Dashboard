// The chart explorer: an SVG scatter (or a rotatable 3D cloud) drawn from /api/chart.
// No dependencies.
(function () {
  "use strict";
  var root = document.getElementById("explorer");
  if (!root) return;

  var NS = "http://www.w3.org/2000/svg";
  var svg = document.getElementById("c-svg");
  var plot = document.getElementById("plot");
  var tip = document.getElementById("tip");
  var $ = function (id) { return document.getElementById("c-" + id); };
  var MENUS = JSON.parse(document.getElementById("c-menus").textContent);
  var PRESETS = JSON.parse(document.getElementById("c-presets-data").textContent);
  var init = JSON.parse(document.getElementById("c-state").textContent);
  var DEFAULTS = { team: ["pit:ERA", "bat:wRC+"], bat: ["wRC+", "WAR"], pit: ["FIP", "ERA"] };
  var LATEST = root.dataset.latest;
  var LADDER = [0, 1, 5, 10];
  (function () {
    var n;
    for (n = 20; n <= 250; n += 10) LADDER.push(n);
    for (n = 300; n <= 1000; n += 50) LADDER.push(n);
    for (n = 1500; n <= 10000; n += 500) LADDER.push(n);
  })();

  var state = {
    view: init.view, kind: init.kind, x: init.x, y: init.y, z: init.z || "",
    season: init.season || LATEST, to: init.to || init.season || LATEST,
    split: init.split === "season" || init.path === "1", path: init.path === "1", era: init.era === "1",
    trend: init.trend === "1", color: init.rank === "1" ? "rank" : (init.color || "rank"),
    logos: init.logos !== "0", mean: init.mean !== "0", min: init.min || "q",
    team: init.team || "", league: init.league || "", pos: init.pos || "",
    find: init.find || "", labels: init.labels || "standouts"
  };
  var data = null, shown = [], pinned = null, hovered = null, loads = 0;
  var rot = { yaw: -0.6, pitch: 0.35 }, drag = null;

  // ------------------------------------------------------------ helpers
  function make(tag, attrs, parent) {
    var node = document.createElementNS(NS, tag);
    for (var key in attrs) node.setAttribute(key, attrs[key]);
    if (parent) parent.appendChild(node);
    return node;
  }
  function fold(text) {
    return String(text || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }
  function show(v, kind) {
    if (v == null) return "";
    if (kind === "pct1") return (v * 100).toFixed(1) + "%";
    if (kind === "avg") return v.toFixed(3).replace(/^(-?)0\./, "$1.");
    if (kind === "d0") return Math.round(v).toLocaleString();
    if (kind === "d1") return v.toFixed(1);
    if (kind === "ip") { var outs = Math.round(v * 3); return Math.floor(outs / 3).toLocaleString() + "." + (outs % 3); }
    if (kind === "pctl") return Math.round(v) + "th pct";
    return v.toFixed(2);
  }
  function tickText(v, kind, step) {
    if (kind === "pct1") return (v * 100).toFixed(step * 100 < 1 ? 1 : 0) + "%";
    if (kind === "avg") return v.toFixed(step < 0.01 ? 3 : 2).replace(/^(-?)0\./, "$1.");
    if (kind === "ip") return Math.round(v).toLocaleString();
    if (kind === "pctl") return Math.round(v);
    var d = step < 0.1 ? 2 : step < 1 ? 1 : 0;
    return Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(d);
  }
  function ticks(lo, hi, want) {
    var raw = (hi - lo) / Math.max(want, 1);
    var power = Math.pow(10, Math.floor(Math.log10(raw)));
    var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * power; })
      .filter(function (s) { return s >= raw; })[0] || raw;
    var out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return { values: out, step: step };
  }
  function ramp(t) {
    var stops = [[229, 72, 77], [249, 115, 22], [70, 167, 88]];
    t = Math.max(0, Math.min(1, t));
    var i = t < 0.5 ? 0 : 1, k = (t - i * 0.5) / 0.5;
    var c = stops[i].map(function (a, j) { return Math.round(a + (stops[i + 1][j] - a) * k); });
    return "rgb(" + c.join(",") + ")";
  }
  function percentile(rows, key, better) {
    var sorted = rows.map(function (r) { return r[key]; }).sort(function (a, b) { return a - b; });
    var n = sorted.length;
    rows.forEach(function (row) {
      var lo = 0, hi = n;
      while (lo < hi) { var mid = (lo + hi) >> 1; if (sorted[mid] < row[key]) lo = mid + 1; else hi = mid; }
      var below = lo, end = lo;
      while (end < n && sorted[end] === row[key]) end++;
      var share = n > 1 ? (below + (end - below - 1) / 2) / (n - 1) : 0.5;
      row["_p" + key] = better ? share : 1 - share;
    });
  }
  function key() { return state.view === "team" ? "team" : state.kind; }
  function menu() {
    if (state.view === "player") return MENUS[state.kind].map(function (g) { return [g[0], g[1], ""]; });
    var out = [];
    MENUS.bat.forEach(function (g) { out.push(["Hitting: " + g[0], g[1], "bat:"]); });
    MENUS.pit.forEach(function (g) { out.push(["Pitching: " + g[0], g[1], "pit:"]); });
    return out;
  }
  var COLS = {};
  function indexColumns() {
    COLS = {};
    menu().forEach(function (g) { g[1].forEach(function (c) { COLS[g[2] + c[0]] = c; }); });
  }
  var TEAM_COLORS = {};

  // ------------------------------------------------------------ controls
  function fillSelect(select, options, value) {
    select.textContent = "";
    options.forEach(function (o) { select.appendChild(new Option(o[1], o[0])); });
    select.value = value;
  }
  function fillStats() {
    indexColumns();
    ["x", "y", "z"].forEach(function (id) {
      var select = $(id);
      select.textContent = "";
      if (id === "z") select.appendChild(new Option("None (2D)", ""));
      menu().forEach(function (g) {
        var box = document.createElement("optgroup");
        box.label = g[0];
        g[1].forEach(function (c) {
          var head = c[4] || c[0];
          var label = head + (c[1] && c[1] !== head ? "  \u00b7  " + c[1] : "");
          box.appendChild(new Option(label, g[2] + c[0]));
        });
        select.appendChild(box);
      });
      if (state[id] && !COLS[state[id]]) state[id] = id === "z" ? "" : DEFAULTS[key()][id === "x" ? 0 : 1];
      select.value = state[id];
    });
    var presets = $("presets");
    presets.textContent = "";
    PRESETS[key()].forEach(function (p) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = p[0];
      b.addEventListener("click", function () { state.x = p[1]; state.y = p[2]; state.z = ""; fillStats(); load(); });
      presets.appendChild(b);
    });
  }
  function syncControls() {
    Array.prototype.forEach.call($("view").children, function (b) { b.classList.toggle("on", b.dataset.v === state.view); });
    Array.prototype.forEach.call($("kind").children, function (b) { b.classList.toggle("on", b.dataset.v === state.kind); });
    var players = state.view === "player";
    $("kind").hidden = !players;
    $("player-filters").hidden = !players;
    $("team-field").hidden = !players;
    $("logos-row").hidden = players;
    $("season").value = state.season; $("to").value = state.to;
    var unit = state.kind === "pit" ? "IP" : "PA";
    $("min-label").textContent = "Min " + unit;
    var span = +state.to !== +state.season;
    // FanGraphs' ladder (62 options with Qualified), for seasons and spans alike.
    var nums = LADDER.slice();
    if (state.min !== "q" && nums.indexOf(+state.min) === -1) nums.push(+state.min);
    nums.sort(function (a, b) { return a - b; });
    var opts = [["q", "Qualified"]].concat(nums.map(function (n) { return [String(n), n.toLocaleString()]; }));
    opts.push(["__custom", "Other number\u2026"]);
    fillSelect($("min"), opts, state.min);
    var pos = state.kind === "pit" ? [["", "All"], ["SP", "Starters"], ["RP", "Relievers"]]
      : [["", "All"], ["C", "C"], ["1B", "1B"], ["2B", "2B"], ["3B", "3B"], ["SS", "SS"], ["OF", "OF"], ["DH", "DH"]];
    fillSelect($("pos"), pos, state.pos);
    $("team").value = state.team; $("league").value = state.league;
    $("split").checked = state.split; $("path").checked = state.path; $("era").checked = state.era;
    $("split").disabled = !span; $("path").disabled = !span;
    $("find").value = state.find; $("labels").value = state.labels; $("color").value = state.color;
    $("mean").checked = state.mean; $("trend").checked = state.trend; $("logos").checked = state.logos;
  }
  function params(forUrl) {
    var out = new URLSearchParams();
    var d = DEFAULTS[key()];
    if (state.view !== "team") out.set("view", state.view);
    if (state.view === "player" && state.kind !== "bat") out.set("kind", state.kind);
    if (!forUrl || state.season !== LATEST || state.to !== LATEST) out.set("season", state.season);
    if (state.to !== state.season) out.set("to", state.to);
    if (!forUrl || state.x !== d[0]) out.set("x", state.x);
    if (!forUrl || state.y !== d[1]) out.set("y", state.y);
    if (state.z) out.set("z", state.z);
    var span = state.to !== state.season;
    if (span && state.split) out.set("split", "season");
    if (span && state.path) out.set("path", "1");
    if (state.era) out.set("era", "1");
    if (state.view === "player") {
      if (state.min !== "q") out.set("min", state.min);
      if (state.team) out.set("team", state.team);
      if (state.pos) out.set("pos", state.pos);
    }
    if (state.league) out.set("league", state.league);
    if (forUrl) {
      if (state.trend) out.set("trend", "1");
      if (state.color !== "rank") out.set("color", state.color);
      if (!state.mean) out.set("mean", "0");
      if (!state.logos) out.set("logos", "0");
      if (state.labels !== "standouts") out.set("labels", state.labels);
      if (state.find) out.set("find", state.find);
    }
    return out.toString();
  }
  function writeUrl() {
    var text = params(true);
    history.replaceState(null, "", window.location.pathname + (text ? "?" + text : ""));
  }

  // ---------------------------------------------------------------- data
  function load() {
    var ticket = ++loads;
    $("count").textContent = "Loading\u2026";
    writeUrl();
    fetch("/api/chart?" + params(false)).then(function (r) { return r.json(); }).then(function (payload) {
      if (ticket !== loads) return;
      if (payload.error) { data = null; drawMessage(payload.error); return; }
      data = payload;
      data.rows = payload.rows.map(function (values) {
        var row = {};
        payload.fields.forEach(function (f, i) { row[f] = values[i]; });
        return row;
      });
      pinned = null; hovered = null; tip.hidden = true;
      draw();
    }).catch(function () { drawMessage("Could not load the data. Reload to try again."); });
  }
  function drawMessage(text) {
    svg.textContent = "";
    var width = Math.max(300, Math.floor(plot.clientWidth - 20)), height = 320;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("width", width); svg.setAttribute("height", height);
    make("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "axis-title" }, svg).textContent = text;
    $("count").textContent = ""; $("board").textContent = ""; $("title").textContent = "";
  }

  // ---------------------------------------------------------------- draw
  function update() { pinned = null; hovered = null; tip.hidden = true; writeUrl(); draw(); }

  function draw() {
    if (!data) return;
    var ax = data.axes.x, ay = data.axes.y, az = data.axes.z;
    shown = data.rows;
    var players = data.view === "player";
    var width = Math.max(300, Math.floor(plot.clientWidth - 20));
    var narrow = width < 560;
    var height = Math.round(Math.max(320, Math.min(660, width * (narrow ? 0.95 : 0.6))));
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("width", width); svg.setAttribute("height", height);
    svg.textContent = "";
    $("title").textContent = ay.label + " against " + ax.label + (az ? " and " + az.label : "") + (data.era ? " (season percentiles)" : "");
    var who = players ? (data.kind === "pit" ? "pitchers" : "hitters") : "teams";
    $("count").textContent = shown.length.toLocaleString() + " " + (data.split ? (players ? "player" : "team") + "-seasons" : who) +
      " \u00b7 " + data.label + (data.need ? " \u00b7 " + data.need : "") + (data.notes.length ? " \u00b7 " + data.notes.join(" ") : "");
    if (!shown.length) {
      drawMessage(players ? "No players match. Lower the minimum or widen the filters." : "No teams match.");
      return;
    }
    if (data.era) {
      // Era values are already season percentiles (100 = best) against the full
      // pool; re-ranking the visible points would undo the filters fix.
      shown.forEach(function (r) {
        r._px = r.x / 100; r._py = r.y / 100;
        if (az) r._pz = r.z / 100;
      });
    } else {
      percentile(shown, "x", ax.better);
      percentile(shown, "y", ay.better);
      if (az) percentile(shown, "z", az.better);
    }
    shown.forEach(function (r) { r._score = az ? (r._px + r._py + r._pz) / 3 : (r._px + r._py) / 2; });
    var needle = fold(state.find.trim());
    shown.forEach(function (r) {
      r._hit = !!needle && fold(r.name + " " + r.team + (r.season ? " " + r.season : "")).indexOf(needle) !== -1;
    });
    if (az) draw3d(width, height, narrow); else draw2d(width, height, narrow, players, needle);
    drawBoard(players);
  }

  function seasonTag(r) { return r.season ? " \u2019" + String(r.season).slice(2) : ""; }

  function draw2d(width, height, narrow, players, needle) {
    var ax = data.axes.x, ay = data.axes.y;
    var m = { l: narrow ? 42 : 56, r: 14, t: 10, b: narrow ? 38 : 44 };
    function extent(k) {
      var lo = Infinity, hi = -Infinity;
      shown.forEach(function (r) { lo = Math.min(lo, r[k]); hi = Math.max(hi, r[k]); });
      var pad = (hi - lo) * 0.07 || Math.abs(hi) * 0.05 || 1;
      return [lo - pad, hi + pad];
    }
    var ex = extent("x"), ey = extent("y");
    var pw = width - m.l - m.r, ph = height - m.t - m.b;
    // "Better" points right and up: lower-is-better axes are flipped.
    function sx(v) { var t = (v - ex[0]) / (ex[1] - ex[0]); return m.l + (ax.better ? t : 1 - t) * pw; }
    function sy(v) { var t = (v - ey[0]) / (ey[1] - ey[0]); return m.t + (ay.better ? 1 - t : t) * ph; }
    var tx = ticks(ex[0], ex[1], narrow ? 4 : 7), ty = ticks(ey[0], ey[1], narrow ? 5 : 6);
    tx.values.forEach(function (v) {
      make("line", { class: "gridline", x1: sx(v), x2: sx(v), y1: m.t, y2: m.t + ph }, svg);
      make("text", { class: "axis", x: sx(v), y: m.t + ph + 14, "text-anchor": "middle" }, svg).textContent = tickText(v, ax.fmt, tx.step);
    });
    ty.values.forEach(function (v) {
      make("line", { class: "gridline", x1: m.l, x2: m.l + pw, y1: sy(v), y2: sy(v) }, svg);
      make("text", { class: "axis", x: m.l - 6, y: sy(v) + 3.5, "text-anchor": "end" }, svg).textContent = tickText(v, ay.fmt, ty.step);
    });
    make("text", { class: "axis-title", x: m.l + pw / 2, y: height - 6, "text-anchor": "middle" }, svg)
      .textContent = ax.label + (ax.better ? "" : "  (lower is better, axis flipped)");
    make("text", { class: "axis-title", "text-anchor": "middle", transform: "translate(12," + (m.t + ph / 2) + ") rotate(-90)" }, svg)
      .textContent = ay.label + (ay.better ? "" : "  (flipped)");

    if (state.mean) {
      var mx = 0, my = 0;
      shown.forEach(function (r) { mx += r.x; my += r.y; });
      mx /= shown.length; my /= shown.length;
      make("line", { class: "mean", x1: sx(mx), x2: sx(mx), y1: m.t, y2: m.t + ph }, svg);
      make("line", { class: "mean", x1: m.l, x2: m.l + pw, y1: sy(my), y2: sy(my) }, svg);
      make("text", { class: "axis", x: sx(mx) + 4, y: m.t + 10 }, svg).textContent = "avg " + show(mx, ax.fmt);
      make("text", { class: "axis", x: m.l + pw - 4, y: sy(my) - 4, "text-anchor": "end" }, svg).textContent = "avg " + show(my, ay.fmt);
    }
    if (state.trend && shown.length > 2) {
      var n = shown.length, sxv = 0, syv = 0, sxx = 0, sxy = 0, syy = 0;
      shown.forEach(function (r) { sxv += r.x; syv += r.y; sxx += r.x * r.x; sxy += r.x * r.y; syy += r.y * r.y; });
      var vx = sxx - sxv * sxv / n, vy = syy - syv * syv / n, cxy = sxy - sxv * syv / n;
      if (vx > 0 && vy > 0) {
        var slope = cxy / vx, icpt = (syv - slope * sxv) / n, r2 = cxy * cxy / (vx * vy);
        var x0 = ex[0], x1 = ex[1];
        var y0 = slope * x0 + icpt, y1 = slope * x1 + icpt;
        var clip = make("clipPath", { id: "c-clip" }, svg);
        make("rect", { x: m.l, y: m.t, width: pw, height: ph }, clip);
        make("line", { class: "trend", x1: sx(x0), y1: sy(y0), x2: sx(x1), y2: sy(y1), "clip-path": "url(#c-clip)" }, svg);
        make("text", { class: "axis trend-label", x: m.l + 6, y: m.t + ph - 8 }, svg)
          .textContent = "trend r\u00b2 = " + r2.toFixed(2) + (cxy < 0 ? " (negative)" : "");
      }
    }
    shown.forEach(function (r) { r._x = sx(r.x); r._y = sy(r.y); r._r = players ? (shown.length > 1500 ? 3 : 4.4) : 7; });

    // Trajectories: each one's seasons in order.
    if (data.split && state.path) {
      var groups = {};
      shown.forEach(function (r) { (groups[r.id] = groups[r.id] || []).push(r); });
      var ids = Object.keys(groups);
      var chosen = needle ? ids.filter(function (id) { return groups[id].some(function (r) { return r._hit; }); })
        : ids.map(function (id) {
            var g = groups[id], s = 0; g.forEach(function (r) { s += r._score; }); return [id, s / g.length * Math.min(g.length, 6)];
          }).sort(function (a, b) { return b[1] - a[1]; }).slice(0, players ? 10 : 8).map(function (p) { return p[0]; });
      chosen.forEach(function (id, i) {
        var g = groups[id].sort(function (a, b) { return a.season - b.season; });
        if (g.length < 2) return;
        var color = ["#f97316", "#60a5fa", "#3ecf8e", "#e879f9", "#facc15", "#f2555a", "#22d3ee", "#a3e635", "#fb7185", "#c4b5fd"][i % 10];
        make("polyline", { class: "path", points: g.map(function (r) { return r._x + "," + r._y; }).join(" "), stroke: color }, svg);
        g.forEach(function (r) { r._path = color; });
        var last = g[g.length - 1];
        make("text", { class: "lbl", x: last._x + 7, y: last._y + 4, fill: color }, svg).textContent = shortName(last.name, narrow);
      });
    }

    var logos = !players && state.logos;
    var layer = make("g", {}, svg);
    var faded = !!needle || (data.split && state.path);
    shown.slice().sort(function (a, b) { return (a._hit - b._hit) || (!!a._path - !!b._path); }).forEach(function (r) {
      var on = r._hit || r._path;
      var group = make("g", { class: "pt" + (faded && !on ? " faded" : "") + (r._hit ? " hit" : "") }, layer);
      var size = narrow ? 22 : 28;
      if (logos && r.logo) {
        make("image", { href: r.logo, x: r._x - size / 2, y: r._y - size / 2, width: size, height: size, preserveAspectRatio: "xMidYMid meet" }, group);
        r._r = size / 2;
      } else if (logos) {
        // No logo that season: a square with the club's code, in its color when known.
        var side = size * 0.8, code = String(r.team || "").slice(0, 4);
        var color = TEAM_COLORS[r.team] || "#334155";
        make("rect", { x: r._x - side / 2, y: r._y - side / 2, width: side, height: side, rx: 4, fill: color, stroke: "rgba(255,255,255,0.35)", "stroke-width": 1 }, group);
        make("text", { x: r._x, y: r._y + 3.2, "text-anchor": "middle", class: "codesq", "font-size": code.length > 3 ? 7.5 : 9 }, group).textContent = code;
        r._r = side / 2;
      } else {
        var fill = r._path ? r._path : state.color === "rank" ? ramp(r._score)
          : state.color === "team" ? teamColor(r.team) : "#7fa3d9";
        make("circle", { cx: r._x, cy: r._y, r: r._r, fill: fill, "fill-opacity": players ? 0.85 : 1 }, group);
      }
    });
    labels2d(width, height, narrow, players, m, ph, logos);
  }

  function labels2d(width, height, narrow, players, m, ph, logos) {
    var want = state.labels === "none" ? 0 : state.labels === "all" ? shown.length
      : state.labels === "more" ? (narrow ? 16 : 36) : (narrow ? 8 : 16);
    if (!players && !logos && state.labels !== "none") want = shown.length;
    if (!players && logos && state.labels === "standouts") want = 0;
    if (players && state.team && state.labels === "standouts") want = Math.min(shown.length, 40);
    var order = shown.slice().sort(function (a, b) {
      function reach(r) {
        var dx = r._px - 0.5, dy = r._py - 0.5;
        return (dx * dx + dy * dy) * (0.3 + 0.7 * r._score) + 0.35 * Math.max(dy, 0);
      }
      return (b._hit - a._hit) || (reach(b) - reach(a));
    });
    var hits = order.filter(function (r) { return r._hit; }).length;
    var boxes = [];
    function free(box) {
      if (box.x < m.l - 2 || box.x + box.w > width - 2 || box.y < m.t - 2 || box.y + box.h > m.t + ph + 2) return false;
      return !boxes.some(function (o) { return box.x < o.x + o.w && box.x + box.w > o.x && box.y < o.y + o.h && box.y + box.h > o.y; });
    }
    order.slice(0, Math.max(want, Math.min(hits, 24))).forEach(function (r) {
      var text = (players ? shortName(r.name, narrow) : r.team) + (data.split ? seasonTag(r) : "");
      var w = text.length * 6.1 + 4, h = 13, gap = r._r + 3;
      var spots = [
        { x: r._x + gap, y: r._y - h / 2 }, { x: r._x - gap - w, y: r._y - h / 2 },
        { x: r._x - w / 2, y: r._y - gap - h }, { x: r._x - w / 2, y: r._y + gap },
        { x: r._x + gap * 0.7, y: r._y - gap - h * 0.6 }, { x: r._x - gap * 0.7 - w, y: r._y + gap * 0.4 }
      ];
      for (var i = 0; i < spots.length; i++) {
        var box = { x: spots[i].x, y: spots[i].y, w: w, h: h };
        if (free(box)) {
          boxes.push(box);
          make("text", { class: "lbl" + (r._hit ? " hit" : ""), x: box.x + 2, y: box.y + h - 3 }, svg).textContent = text;
          break;
        }
      }
    });
  }

  // 3D: an orthographic projection of the unit cube; drag to rotate.
  function draw3d(width, height, narrow) {
    var axes = data.axes;
    var ext = {};
    ["x", "y", "z"].forEach(function (k) {
      var lo = Infinity, hi = -Infinity;
      shown.forEach(function (r) { lo = Math.min(lo, r[k]); hi = Math.max(hi, r[k]); });
      if (hi === lo) { hi += 1; lo -= 1; }
      ext[k] = [lo, hi];
    });
    function unit(r, k) { var t = (r[k] - ext[k][0]) / (ext[k][1] - ext[k][0]); return (axes[k].better ? t : 1 - t) * 2 - 1; }
    var cy = Math.cos(rot.yaw), sy = Math.sin(rot.yaw), cp = Math.cos(rot.pitch), sp = Math.sin(rot.pitch);
    var scale = Math.min(width, height) * 0.3, ox = width / 2, oy = height / 2 + 10;
    function project(x, y, z) {   // x right, y up, z depth
      var x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
      var y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
      return [ox + x1 * scale, oy - y2 * scale, z2];
    }
    var corners = [];
    [-1, 1].forEach(function (a) { [-1, 1].forEach(function (b) { [-1, 1].forEach(function (c) { corners.push([a, b, c]); }); }); });
    corners.forEach(function (p, i) {
      corners.forEach(function (q, j) {
        if (j <= i) return;
        var diff = Math.abs(p[0] - q[0]) + Math.abs(p[1] - q[1]) + Math.abs(p[2] - q[2]);
        if (diff !== 2) return;
        var a = project(p[0], p[1], p[2]), b = project(q[0], q[1], q[2]);
        make("line", { class: "gridline", x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, svg);
      });
    });
    [["x", [1.25, -1, -1]], ["y", [-1, 1.2, -1]], ["z", [-1, -1, 1.3]]].forEach(function (e) {
      var p = project(e[1][0], e[1][1], e[1][2]);
      make("text", { class: "axis-title", x: p[0], y: p[1], "text-anchor": "middle" }, svg).textContent = axes[e[0]].label;
    });
    shown.forEach(function (r) {
      var p = project(unit(r, "x"), unit(r, "y"), unit(r, "z"));
      r._x = p[0]; r._y = p[1]; r._d = p[2]; r._r = data.view === "player" ? 4 : 6;
    });
    var faded = shown.some(function (r) { return r._hit; });
    shown.slice().sort(function (a, b) { return a._d - b._d; }).forEach(function (r) {
      var g = make("g", { class: "pt" + (faded && !r._hit ? " faded" : "") + (r._hit ? " hit" : "") }, svg);
      var depth = 0.55 + 0.45 * (r._d + 1.8) / 3.6;
      make("circle", { cx: r._x, cy: r._y, r: r._r * depth + 1, fill: state.color === "team" ? teamColor(r.team) : ramp(r._score), "fill-opacity": 0.9 }, g);
    });
    shown.filter(function (r) { return r._hit; }).slice(0, 20).concat(
      state.labels === "none" || faded ? [] : shown.slice().sort(function (a, b) { return b._score - a._score; }).slice(0, narrow ? 5 : 10)
    ).forEach(function (r) {
      make("text", { class: "lbl" + (r._hit ? " hit" : ""), x: r._x + r._r + 3, y: r._y + 4 }, svg)
        .textContent = (data.view === "player" ? shortName(r.name, narrow) : r.team) + (data.split ? seasonTag(r) : "");
    });
    make("text", { class: "axis", x: 8, y: height - 8 }, svg).textContent = "Drag to rotate. Better is right, up and toward you.";
  }

  function teamColor(code) { return TEAM_COLORS[code] || "#7fa3d9"; }

  function drawBoard(players) {
    var board = $("board");
    board.textContent = "";
    $("board-title").textContent = data.axes.z ? "Best on all three axes" : "Best on both axes";
    shown.slice().sort(function (a, b) { return b._score - a._score; }).slice(0, 10).forEach(function (r, i) {
      var item = document.createElement("li");
      var rank = document.createElement("i"); rank.textContent = i + 1;
      var link = document.createElement("a");
      link.href = players ? "/player/" + r.id : "/team/" + r.team + "?season=" + (r.season || r.last || data.hi);
      link.textContent = r.name + (r.season && data.split ? " " + r.season : "");
      var value = document.createElement("b"); value.textContent = Math.round(r._score * 100);
      item.appendChild(rank); item.appendChild(link); item.appendChild(value);
      board.appendChild(item);
    });
  }

  function shortName(name, narrow) {
    var parts = String(name).split(" ");
    if (parts.length < 2) return name;
    return narrow || name.length > 16 ? parts[0].charAt(0) + ". " + parts.slice(1).join(" ") : name;
  }

  // -------------------------------------------------------------- pointer
  function nearest(event) {
    var box = svg.getBoundingClientRect();
    var scale = (svg.viewBox.baseVal.width || box.width) / box.width;
    var px = (event.clientX - box.left) * scale, py = (event.clientY - box.top) * scale;
    var best = null, bestD = Infinity;
    shown.forEach(function (r) {
      var d = Math.hypot(r._x - px, r._y - py) - r._r * 0.6;
      if (d < bestD) { bestD = d; best = r; }
    });
    return bestD <= 22 ? best : null;
  }
  function line(label, value) {
    var row = document.createElement("span");
    var a = document.createElement("i"); a.textContent = label; a.style.fontStyle = "normal";
    var b = document.createElement("strong"); b.textContent = value; b.style.color = "var(--text)";
    row.appendChild(a); row.appendChild(b);
    return row;
  }
  function showTip(r, pin) {
    if (!r || !data) { tip.hidden = true; return; }
    tip.textContent = "";
    var name = document.createElement("b");
    var span = r.season ? r.season : (r.first && r.last && r.first !== r.last ? r.first + "\u2013" + r.last : (r.first || ""));
    name.textContent = r.name + "  " + (data.view === "player" ? (r.team === "- - -" ? "2+ teams" : r.team) + " " : "") + span;
    tip.appendChild(name);
    if (data.view === "team" && r.lg) {   // "Chicago Pirates (1890, Players' League)"
      var lgline = document.createElement("span");
      lgline.textContent = r.team + " \u00b7 " + r.lg;
      lgline.style.cssText = "display:block;color:var(--muted);font-size:12px";
      tip.appendChild(lgline);
    }
    ["y", "x", "z"].forEach(function (k) {
      var a = data.axes[k];
      if (a) tip.appendChild(line(a.label, show(r[k], a.fmt)));
    });
    if (data.view === "player" && r.w != null) tip.appendChild(line(data.kind === "pit" ? "IP" : "PA", show(r.w, data.kind === "pit" ? "ip" : "d0")));
    if (pin) {
      var link = document.createElement("a");
      link.href = data.view === "player" ? "/player/" + r.id : "/team/" + r.team + "?season=" + (r.season || r.last || data.hi);
      link.textContent = "Open " + (data.view === "player" ? "player" : "team") + " page";
      link.style.cssText = "display:block;margin-top:6px;color:var(--accent);font-weight:600";
      tip.appendChild(link);
    }
    tip.style.pointerEvents = pin ? "auto" : "none";
    tip.hidden = false;
    var box = svg.getBoundingClientRect(), host = plot.getBoundingClientRect();
    var scale = box.width / (svg.viewBox.baseVal.width || box.width);
    var left = box.left - host.left + r._x * scale + 14, top = box.top - host.top + r._y * scale - 10;
    if (left + tip.offsetWidth > host.width - 6) left -= tip.offsetWidth + 28;
    if (top + tip.offsetHeight > host.height - 6) top = host.height - tip.offsetHeight - 6;
    tip.style.left = Math.max(4, left) + "px";
    tip.style.top = Math.max(4, top) + "px";
  }
  svg.addEventListener("pointerdown", function (event) {
    if (!data || !data.axes.z) return;
    drag = { x: event.clientX, y: event.clientY, yaw: rot.yaw, pitch: rot.pitch, moved: false };
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", function (event) {
    if (drag) {
      var dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      rot.yaw = drag.yaw + dx * 0.01;
      rot.pitch = Math.max(-1.4, Math.min(1.4, drag.pitch + dy * 0.01));
      tip.hidden = true;
      draw();
      return;
    }
    if (pinned || event.pointerType === "touch") return;
    var r = nearest(event);
    if (r !== hovered) { hovered = r; showTip(r, false); }
    svg.style.cursor = r ? "pointer" : (data && data.axes.z ? "grab" : "default");
  });
  svg.addEventListener("pointerup", function () { setTimeout(function () { drag = null; }, 0); });
  svg.addEventListener("pointerleave", function () { if (!pinned) { hovered = null; tip.hidden = true; } });
  svg.addEventListener("click", function (event) {
    if (drag && drag.moved) return;
    var r = nearest(event);
    pinned = r && r !== pinned ? r : null;
    showTip(pinned, true);
  });

  // -------------------------------------------------------------- CSV
  function csv() {
    if (!data) return;
    var a = data.axes, head = ["name", "team", "season", "first", "last", data.kind === "pit" && data.view === "player" ? "IP" : "PA"];
    ["x", "y", "z"].forEach(function (k) { if (a[k]) head.push(a[k].label + (data.era ? " (percentile)" : "")); });
    head.push("composite percentile");
    var lines = [head];
    // Rounded like the screen (FanGraphs' precision); percentages stay fractions, as FanGraphs exports them.
    function round(v, kind) {
      if (v == null) return "";
      if (kind === "pct1") return +v.toFixed(3);
      if (kind === "avg") return +v.toFixed(3);
      if (kind === "d0" || kind === "pctl") return Math.round(v);
      if (kind === "d1") return +v.toFixed(1);
      if (kind === "ip") return show(v, "ip");
      return +v.toFixed(2);
    }
    var unit = data.kind === "pit" && data.view === "player" ? "ip" : "d0";
    shown.slice().sort(function (p, q) { return q._score - p._score; }).forEach(function (r) {
      var row = [r.name, r.team, r.season || "", r.first || "", r.last || "", round(r.w, unit)];
      ["x", "y", "z"].forEach(function (k) { if (a[k]) row.push(round(r[k], a[k].fmt)); });
      row.push(Math.round(r._score * 100));
      lines.push(row);
    });
    var text = lines.map(function (row) {
      return row.map(function (v) { v = String(v == null ? "" : v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }).join(",");
    }).join("\n");
    var link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    link.download = "baseball-" + (data.view === "player" ? data.kind : "teams") + "-" + data.lo + (data.hi !== data.lo ? "-" + data.hi : "") + ".csv";
    document.body.appendChild(link); link.click(); link.remove();
  }

  // -------------------------------------------------------------- wiring
  $("view").addEventListener("click", function (event) {
    var v = event.target.dataset.v;
    if (!v || v === state.view) return;
    state.view = v; state.x = DEFAULTS[key()][0]; state.y = DEFAULTS[key()][1]; state.z = ""; state.find = "";
    fillStats(); syncControls(); load();
  });
  $("kind").addEventListener("click", function (event) {
    var v = event.target.dataset.v;
    if (!v || v === state.kind) return;
    state.kind = v; state.x = DEFAULTS[v][0]; state.y = DEFAULTS[v][1]; state.z = ""; state.pos = ""; state.min = "q";
    fillStats(); syncControls(); load();
  });
  ["season", "to"].forEach(function (id) {
    $(id).addEventListener("change", function () {
      state[id] = this.value;
      if (+state.to < +state.season) { var t = state.to; state.to = state.season; state.season = t; }
      if (state.to === state.season) { state.split = false; state.path = false; }
      if (state.min !== "q" && +state.min >= 1000 && state.to === state.season) state.min = "q";
      syncControls(); load();
    });
  });
  ["x", "y", "z", "pos", "team", "league"].forEach(function (id) {
    $(id).addEventListener("change", function () { state[id] = this.value; load(); });
  });
  $("min").addEventListener("change", function () {
    if (this.value === "__custom") {
      var typed = window.prompt("Minimum " + (state.kind === "pit" ? "IP" : "PA"), "");
      var n = typed == null ? NaN : parseFloat(String(typed).replace(/,/g, ""));
      if (isNaN(n) || n < 0) { this.value = state.min; return; }
      state.min = String(Math.round(n));
      syncControls();
    } else {
      state.min = this.value;
    }
    load();
  });
  $("split").addEventListener("change", function () { state.split = this.checked; if (!this.checked) state.path = false; syncControls(); load(); });
  $("path").addEventListener("change", function () { state.path = this.checked; if (this.checked) state.split = true; syncControls(); load(); });
  $("era").addEventListener("change", function () { state.era = this.checked; load(); });
  ["color", "labels"].forEach(function (id) { $(id).addEventListener("change", function () { state[id] = this.value; update(); }); });
  $("find").addEventListener("input", function () { state.find = this.value; update(); });
  ["mean", "trend", "logos"].forEach(function (id) { $(id).addEventListener("change", function () { state[id] = this.checked; update(); }); });
  $("csv").addEventListener("click", csv);
  $("copy").addEventListener("click", function () {
    var button = this, done = function () { button.textContent = "Link copied"; setTimeout(function () { button.textContent = "Copy link"; }, 1600); };
    if (navigator.clipboard) navigator.clipboard.writeText(window.location.href).then(done, done); else done();
  });
  var timer = null;
  if (window.ResizeObserver) new ResizeObserver(function () { clearTimeout(timer); timer = setTimeout(draw, 60); }).observe(plot);
  else window.addEventListener("resize", draw);
  try { TEAM_COLORS = JSON.parse(root.dataset.colors || "{}"); } catch (e) { TEAM_COLORS = {}; }
  fillStats(); syncControls(); load();
})();
