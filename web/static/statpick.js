/* Searchable stat picker.
 *
 * A <select data-statpick> gets a button that opens a search box over its
 * options: type to filter (abbreviation, full name or group), arrow keys and
 * Enter, or tap a row. data-clear adds an "x" that picks the select's "" option
 * (None / Same for all) in one tap.
 *
 * The <select> stays in the page, hidden, and keeps the value, so code that
 * reads or sets select.value, rebuilds its options, or listens for "change"
 * works as before.
 */
(function () {
  "use strict";
  var VALUE = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  var SEP = /\s+\u00b7\s+/;          // "wRC+  ·  Weighted runs created plus"
  var ICON = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">' +
    '<circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.7"/>' +
    '<path d="M10.6 10.6L14 14" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
  var current = null;               // the open picker
  var count = 0;

  function fold(text) {
    return String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }
  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function escapeRe(text) { return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  function items(select) {
    return Array.prototype.map.call(select.options, function (o) {
      var parts = o.text.split(SEP);
      var parent = o.parentNode;
      return { value: o.value, head: parts[0], name: parts.slice(1).join(" \u00b7 "),
               key: o.value.replace(/^[a-z]+:/, ""),     // "bat:WAR" -> "WAR"
               group: parent && parent.tagName === "OPTGROUP" ? parent.label : "" };
    });
  }

  // Lower is better; -1 = no match. Every typed word must appear in the
  // abbreviation or key, or start a word of the description or group ("era"
  // finds ERA, not "average").
  function score(item, query, words) {
    var short = fold(item.head + " " + item.key);
    var text = fold(item.name + " " + item.group);
    for (var i = 0; i < words.length; i++) {
      if (short.indexOf(words[i]) === -1 && !new RegExp("(^|[^a-z0-9])" + escapeRe(words[i])).test(text)) return -1;
    }
    var head = fold(item.head);
    if (head === query || fold(item.key) === query) return 0;
    if (head.indexOf(query) === 0) return 1;
    if (new RegExp("(^|[^a-z0-9])" + escapeRe(words[0])).test(fold(item.head + " " + item.name))) return 2;
    return head.indexOf(words[0]) !== -1 ? 3 : 4;
  }

  function attach(select) {
    if (select._statpick) return select._statpick;
    var id = "statpick" + (++count);
    var clearable = select.hasAttribute("data-clear");
    var field = select.closest("label");
    var title = field && field.querySelector("span") ? field.querySelector("span").textContent : "";

    var wrap = make("div", "sp");
    var button = make("button", "sp-btn");
    button.type = "button";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.title = "Tap, then type to search";
    var label = make("span", "sp-label");
    var icon = make("span", "sp-icon");
    icon.innerHTML = ICON;
    button.appendChild(label);
    button.appendChild(icon);
    var clear = make("button", "sp-clear", "\u00d7");
    clear.type = "button";
    clear.title = "Clear";
    clear.setAttribute("aria-label", "Clear " + title);
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(button);
    wrap.appendChild(clear);
    wrap.appendChild(select);
    select.classList.add("sp-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    var panel = make("div", "sp-panel");
    panel.hidden = true;
    var input = make("input", "sp-search");
    input.type = "search";
    input.placeholder = "Type to search stats";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("autocapitalize", "off");
    input.setAttribute("autocorrect", "off");
    input.setAttribute("enterkeyhint", "done");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-controls", id + "-list");
    input.setAttribute("aria-label", "Search " + title);
    var list = make("ul", "sp-list");
    list.id = id + "-list";
    list.setAttribute("role", "listbox");
    panel.appendChild(input);
    panel.appendChild(list);
    document.body.appendChild(panel);

    var shown = [];
    var active = -1;
    var picker = { select: select, render: render, open: open, close: close, place: place,
                   contains: function (node) { return wrap.contains(node) || panel.contains(node); } };

    function value() { return VALUE.get.call(select); }

    function render() {
      var option = select.options[select.selectedIndex];
      var parts = option ? option.text.split(SEP) : [""];
      label.textContent = "";
      label.appendChild(make("b", null, parts[0]));
      if (parts.length > 1) label.appendChild(make("span", "sp-name", parts.slice(1).join(" \u00b7 ")));
      button.setAttribute("aria-label", (title ? title + ": " : "") + (option ? option.text : ""));
      clear.hidden = !(clearable && value() !== "");
      button.disabled = select.disabled;
      if (!panel.hidden) fill();
    }

    function row(item, withGroup) {
      var li = make("li", "sp-opt");
      li.id = id + "-o" + shown.length;
      li.setAttribute("role", "option");
      li.dataset.i = shown.length;
      li.appendChild(make("b", null, item.head));
      if (item.name) li.appendChild(make("span", "sp-name", item.name));
      if (withGroup && item.group) li.appendChild(make("span", "sp-grp", item.group));
      if (item.value === value()) { li.classList.add("sel"); li.setAttribute("aria-selected", "true"); }
      shown.push({ value: item.value, li: li });
      list.appendChild(li);
    }

    function fill() {
      var query = fold(input.value.trim());
      var words = query ? query.split(/\s+/) : [];
      var all = items(select);
      list.textContent = "";
      shown = [];
      if (!query) {
        var group = null;
        all.forEach(function (item) {
          if (item.group !== group) {
            group = item.group;
            if (group) list.appendChild(make("li", "sp-group", group));
          }
          row(item, false);
        });
        active = -1;
        shown.forEach(function (s, i) { if (s.value === value()) active = i; });
      } else {
        var ranked = [];
        all.forEach(function (item, order) {
          if (item.value === "") return;
          var s = score(item, query, words);
          if (s >= 0) ranked.push([s, order, item]);
        });
        ranked.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
        ranked.forEach(function (r) { row(r[2], true); });
        if (!ranked.length) list.appendChild(make("li", "sp-empty", "No stat matches \u201c" + input.value.trim() + "\u201d"));
        active = shown.length ? 0 : -1;
      }
      mark();
    }

    function mark(center) {
      shown.forEach(function (s, i) { s.li.classList.toggle("active", i === active); });
      if (active < 0) { input.removeAttribute("aria-activedescendant"); list.scrollTop = 0; return; }
      var li = shown[active].li;
      input.setAttribute("aria-activedescendant", li.id);
      if (center) list.scrollTop = Math.max(0, li.offsetTop - list.clientHeight / 2 + li.offsetHeight / 2);
      else if (li.offsetTop < list.scrollTop) list.scrollTop = li.offsetTop - 24;
      else if (li.offsetTop + li.offsetHeight > list.scrollTop + list.clientHeight) {
        list.scrollTop = li.offsetTop + li.offsetHeight - list.clientHeight;
      }
    }

    function place() {
      var box = wrap.getBoundingClientRect();
      var page = document.documentElement.clientWidth;
      var width = Math.min(Math.max(box.width, 300), 460, page - 16);
      var left = Math.min(Math.max(8, box.left), page - width - 8);
      panel.style.width = width + "px";
      panel.style.left = (left + window.pageXOffset) + "px";
      panel.style.top = (box.bottom + 4 + window.pageYOffset) + "px";
      // Room below the button, above an on-screen keyboard when there is one.
      var view = window.visualViewport;
      var bottom = view ? view.offsetTop + view.height : window.innerHeight;
      var room = bottom - box.bottom - 4 - input.offsetHeight - 30;
      list.style.maxHeight = Math.max(170, Math.min(400, room)) + "px";
    }

    function open(seed) {
      if (current && current !== picker) current.close();
      current = picker;
      input.value = seed || "";
      panel.hidden = false;
      wrap.classList.add("open");
      button.setAttribute("aria-expanded", "true");
      place();
      fill();
      mark(true);
      input.focus({ preventScroll: true });
    }

    function close(refocus) {
      if (panel.hidden) return;
      panel.hidden = true;
      wrap.classList.remove("open");
      button.setAttribute("aria-expanded", "false");
      if (current === picker) current = null;
      if (refocus) button.focus({ preventScroll: true });
    }

    function choose(next) {
      close(true);
      if (next === value()) return;
      select.value = next;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    button.addEventListener("click", function () { if (panel.hidden) open(); else close(true); });
    button.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(); }
      else if (e.key.length === 1 && e.key !== " " && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); open(e.key); }
    });
    clear.addEventListener("click", function (e) { e.preventDefault(); choose(""); });
    input.addEventListener("input", fill);
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!shown.length) return;
        active = active < 0 ? 0 : (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
        mark();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (active >= 0) choose(shown[active].value);
      } else if (e.key === "Escape") {
        e.preventDefault();
        close(true);
      } else if (e.key === "Tab") {
        close(false);
      }
    });
    // Keep the search box focused while a row is pressed (desktop); a tap picks it.
    list.addEventListener("mousedown", function (e) { e.preventDefault(); });
    list.addEventListener("click", function (e) {
      var li = e.target.closest(".sp-opt");
      if (li) choose(shown[+li.dataset.i].value);
    });

    // Follow the select: options rebuilt, value set from code, disabled.
    new MutationObserver(render).observe(select, { childList: true, subtree: true, attributes: true,
                                                   attributeFilter: ["disabled"] });
    Object.defineProperty(select, "value", {
      configurable: true,
      get: function () { return VALUE.get.call(this); },
      set: function (v) { VALUE.set.call(this, v); render(); }
    });
    select.addEventListener("change", render);

    select._statpick = picker;
    render();
    return picker;
  }

  document.addEventListener("pointerdown", function (e) {
    if (current && !current.contains(e.target)) current.close(false);
  }, true);
  // An on-screen keyboard or a rotation changes the room below the button: refit.
  function refit() { if (current) current.place(); }
  window.addEventListener("resize", refit);
  if (window.visualViewport) window.visualViewport.addEventListener("resize", refit);

  document.querySelectorAll("select[data-statpick]").forEach(attach);
  window.StatPick = { attach: attach };
})();
