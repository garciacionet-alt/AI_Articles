/* ==========================================================================
   TiinyMesh · control plane dashboard
   Canonical script source. index.html inlines this file so that GET /ui
   works with no extra static routes. Keep the two in sync (see ui/inline.py).

   If you would rather serve the script separately, replace the inline
   script block in index.html with a tag pointing at mesh-dashboard.js
   (and make sure the gateway serves /ui/mesh-dashboard.js).

   No dependencies. No secrets. The gateway exposes read-only data at
   /mesh/ui without a key.
   ========================================================================== */

(function () {
  "use strict";

  /* ------------------------------------------------------------- config -- */

  // Where the gateway lives. Use the page's own origin when it is http(s)
  // (the gateway serves /ui itself); otherwise fall back to loopback.
  // One place to change.
  var API_BASE =
    location.protocol === "http:" || location.protocol === "https:"
      ? location.origin
      : "http://127.0.0.1:8767";

  var POLL_MS = 15000;
  // The activity panel has its own, faster poll: the point of it is to
  // show what is happening RIGHT NOW, and 15s is too coarse for a
  // gauge that is meant to answer "is this box busy at this moment".
  var ACTIVITY_POLL_MS = 5000;
  // The gateway probes every appliance while it builds the snapshot, so a
  // cold /mesh/ui can take a while. The timeout has to clear that, or the
  // dashboard reports "unreachable" while the gateway is perfectly well.
  var REQUEST_TIMEOUT_MS = 30000;
  var THEME_KEY = "tiiny-mesh.theme";
  var KEY_KEY = "tiiny-mesh.key";
  var MAX_BG_BYTES = 12 * 1024 * 1024;
  var BG_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];

  var CAP_ORDER = ["chat", "embedding", "tts", "asr", "image_gen"];
  var CAP_LABEL = {
    chat: "Chat",
    embedding: "Embedding",
    tts: "Text to speech",
    asr: "Speech to text",
    image_gen: "Image generation"
  };

  /* ------------------------------------------------------------ helpers -- */

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function make(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  // Only touch the DOM when the value actually changed: the dashboard polls
  // every 15s and must not flash or reflow when nothing moved.
  function setText(node, value) {
    if (!node) return;
    var v = value === undefined || value === null ? "" : String(value);
    if (node.textContent !== v) node.textContent = v;
  }

  function setAttr(node, name, value) {
    if (!node) return;
    if (value === undefined || value === null) {
      if (node.hasAttribute(name)) node.removeAttribute(name);
    } else if (node.getAttribute(name) !== String(value)) {
      node.setAttribute(name, String(value));
    }
  }

  function flash(node) {
    if (!node) return;
    node.classList.remove("flash");
    // force a reflow so the animation restarts on a repeated change
    void node.offsetWidth;
    node.classList.add("flash");
  }

  function clamp(n, lo, hi) {
    return Math.min(hi, Math.max(lo, n));
  }

  function fmtInt(n) {
    if (n === undefined || n === null || isNaN(n)) return "—";
    return Number(n).toLocaleString();
  }

  function fmtMs(n) {
    if (n === undefined || n === null || isNaN(n)) return "—";
    return Number(n) >= 1000
      ? (Number(n) / 1000).toFixed(1) + " s"
      : Math.round(Number(n)) + " ms";
  }

  function fmtMb(mb) {
    if (mb === undefined || mb === null || isNaN(mb)) return null;
    var v = Number(mb);
    if (v >= 1024) return (v / 1024).toFixed(1) + " GiB";
    return Math.round(v) + " MB";
  }

  function fmtPct(n) {
    if (n === undefined || n === null || isNaN(n)) return null;
    return (Math.round(Number(n) * 10) / 10).toFixed(1).replace(/\.0$/, "") + "%";
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  }

  /* -------------------------------------------------------------- theme -- */
  /* Three states: system, light, dark. "system" means "follow the OS",
     and it is stored like the other two so the choice survives a reload.
     The inline bootstrap in <head> reads the same key, so there is no
     flash before this script runs. */

  function readStoredTheme() {
    try {
      var v = localStorage.getItem(THEME_KEY);
      return v === "light" || v === "dark" || v === "system" ? v : null;
    } catch (e) {
      return null;
    }
  }

  function writeStoredTheme(mode) {
    try {
      localStorage.setItem(THEME_KEY, mode);
    } catch (e) {
      /* private mode - the choice simply will not persist */
    }
  }

  // The choice the operator made: an explicit light/dark, or system.
  function themeChoice() {
    var s = readStoredTheme();
    return s === "light" || s === "dark" ? s : "system";
  }

  function osPrefersDark() {
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    } catch (e) {
      return true;
    }
  }

  // The Hermes preview frame injects --foreground (and friends) before our
  // styles. A non-empty value means we are running inside that frame.
  function frameForeground() {
    try {
      return getComputedStyle(document.documentElement).getPropertyValue("--foreground").trim();
    } catch (e) {
      return "";
    }
  }

  function isEmbedded() {
    return frameForeground() !== "";
  }

  function parseColor(css) {
    if (!css) return null;
    var s = String(css).trim();
    if (s.charAt(0) === "#") {
      var hex = s.slice(1);
      if (hex.length === 3) {
        hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
      }
      if (hex.length !== 6) return null;
      var n = parseInt(hex, 16);
      if (isNaN(n)) return null;
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    var m = s.match(/rgba?\(\s*([0-9.]+)\s*[,\s]\s*([0-9.]+)\s*[,\s]\s*([0-9.]+)/i);
    if (m) return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3])];
    return null;
  }

  function luminance(rgb) {
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  }

  // Decide the mode: an explicit choice wins, then the frame's own palette
  // (so the widget matches the chat it is embedded in), then the OS.
  function detectMode() {
    var stored = readStoredTheme();
    if (stored === "light" || stored === "dark") return { mode: stored, source: "user" };
    if (isEmbedded()) {
      var rgb = parseColor(frameForeground());
      // a light foreground means the frame itself is a light theme
      return { mode: rgb && luminance(rgb) > 0.5 ? "light" : "dark", source: "auto" };
    }
    return { mode: osPrefersDark() ? "dark" : "light", source: "auto" };
  }

  var currentMode = "dark";

  function applyMode(mode, source) {
    currentMode = mode;
    var html = document.documentElement;
    html.setAttribute("data-theme", mode);
    html.setAttribute("data-mode-source", source);
    updateThemeControl();
  }

  // The control is a three-way segmented group, built by script because
  // the page is a single inlined file with no static markup to spare.
  function buildThemeControl() {
    var old = $("#theme-toggle");
    if (!old || !old.parentNode) return null;
    var seg = make("div", "seg");
    seg.id = "theme-control";
    seg.setAttribute("role", "radiogroup");
    seg.setAttribute("aria-label", "Theme");
    [["system", "System"], ["light", "Light"], ["dark", "Dark"]].forEach(function (pair) {
      var b = make("button", "seg-btn", pair[1]);
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("data-theme-choice", pair[0]);
      b.setAttribute("aria-checked", "false");
      b.addEventListener("click", function () {
        setTheme(pair[0]);
      });
      seg.appendChild(b);
    });
    old.parentNode.replaceChild(seg, old);
    updateThemeControl();
    return seg;
  }

  function updateThemeControl() {
    var seg = $("#theme-control");
    if (!seg) return;
    var choice = themeChoice();
    var buttons = seg.querySelectorAll(".seg-btn");
    for (var i = 0; i < buttons.length; i++) {
      var b = buttons[i];
      var on = b.getAttribute("data-theme-choice") === choice;
      b.setAttribute("aria-checked", on ? "true" : "false");
      b.title =
        b.getAttribute("data-theme-choice") === "system"
          ? "Follow the system appearance"
          : "Always use the " + b.getAttribute("data-theme-choice") + " appearance";
    }
  }

  function setTheme(choice) {
    var c = choice === "light" || choice === "dark" ? choice : "system";
    writeStoredTheme(c);
    var d = detectMode();
    applyMode(d.mode, d.source);
  }

  /* ----------------------------------------------------------- geometry -- */

  /* A policy slot arrives in one of two shapes:
       - the raw string the config holds: "tiiny-ant/Qwen/Qwen3.6-35B-A3B"
       - the resolved form the gateway sends:
         { entry: "...", target: "tiiny-ant", model: "Qwen/Qwen3.6-35B-A3B" }
     The resolved form is better - it has already split the target from the
     model - but the page must survive either, so accept both. */
  function splitRoute(value) {
    if (value === undefined || value === null || value === "") {
      return { target: "", model: "", entry: "" };
    }
    if (typeof value === "object") {
      var target = value.target ? String(value.target) : "";
      var model = value.model ? String(value.model) : "";
      var entry = value.entry ? String(value.entry) : "";
      if (!entry && target) entry = model ? target + "/" + model : target;
      return { target: target, model: model, entry: entry };
    }
    var s = String(value);
    var i = s.indexOf("/");
    if (i === -1) return { target: s, model: "", entry: s };
    return { target: s.slice(0, i), model: s.slice(i + 1), entry: s };
  }

  function kindFamily(kind) {
    var k = String(kind || "").toLowerCase();
    if (k === "tiiny" || k === "appliance" || k === "device") return "tiiny";
    if (k === "anthropic") return "anthropic";
    if (k === "cloud" || k === "paid" || k === "remote") return "cloud";
    if (k === "openai" || k === "openai-compatible" || k === "ollama" || k === "lmstudio" || k === "local") {
      return "openai";
    }
    return "other";
  }

  function healthState(t) {
    var h = String(t && t.health || "").toLowerCase();
    if (h === "up" || h === "ok" || h === "healthy" || h === "online") return "up";
    if (h === "down" || h === "offline" || h === "error" || h === "failed") return "down";
    if (h) return "degraded";
    return t && t.http && t.http >= 200 && t.http < 400 ? "up" : "down";
  }

  /* -------------------------------------------------------------- state -- */

  var state = {
    data: null,
    error: null,
    lastOk: 0,
    loading: false
  };

  var policyCards = new Map();
  var targetCards = new Map();
  var kindByTarget = {};

  // What the editor needs to know about the estate: the targets by id and
  // the models each target offers for each capability.
  var targetInfo = {};
  var targetOrder = [];
  var modelsByCap = {};

  function indexTargets(targets) {
    targetInfo = {};
    targetOrder = [];
    var list = Array.isArray(targets) ? targets : [];
    list.forEach(function (t) {
      if (!t || !t.id) return;
      targetInfo[t.id] = t;
      targetOrder.push(t.id);
    });
  }

  function indexModels(capabilities) {
    modelsByCap = {};
    Object.keys(capabilities || {}).forEach(function (cap) {
      var info = capabilities[cap] || {};
      var available = Array.isArray(info.available) ? info.available : [];
      var byTarget = {};
      available.forEach(function (meshId) {
        var parts = splitRoute(meshId);
        if (!parts.target) return;
        if (!byTarget[parts.target]) byTarget[parts.target] = [];
        byTarget[parts.target].push(parts.model);
      });
      modelsByCap[cap] = byTarget;
    });
  }

  // A short, human name for a target, taken from its own note:
  // "TinyAnt - the pinned vault box. ..." -> "TinyAnt".
  function shortName(t) {
    var note = String((t && t.note) || "");
    var s = note.split(/[.:;]/)[0];
    s = s.split(" - ")[0];
    s = s.trim();
    if (!s) return (t && t.id) || "target";
    if (s.length > 34) s = s.slice(0, 33) + "…";
    return s;
  }

  /* ------------------------------------------------------------- render -- */

  function computeRoles(policy) {
    var map = {};
    function add(targetId, cap, role) {
      if (!targetId) return;
      if (!map[targetId]) map[targetId] = { primary: [], secondary: [] };
      if (map[targetId][role].indexOf(cap) === -1) map[targetId][role].push(cap);
    }
    Object.keys(policy || {}).forEach(function (cap) {
      var entry = policy[cap] || {};
      add(splitRoute(entry.primary).target, cap, "primary");
      add(splitRoute(entry.secondary).target, cap, "secondary");
    });
    return map;
  }

  function kindColorFor(targetId) {
    var family = kindByTarget[targetId];
    if (!family) return "var(--tm-kind-other, #94a3b8)";
    return "var(--tm-kind-" + family + ", #94a3b8)";
  }

  function buildPolicyCard(cap) {
    var card = make("article", "card policy-card");
    card.setAttribute("data-cap", cap);

    var head = make("div", "pc-head");
    var h3 = make("h3", null, CAP_LABEL[cap] || cap);
    h3.id = "pc-h-" + cap;
    head.appendChild(h3);
    var meta = make("span", "pc-meta");
    head.appendChild(meta);

    var route = make("div", "route");

    var roleP = make("span", "role primary", "Primary");
    var chipP = make("span", "chip chip-primary");
    var dotP = make("span", "kdot");
    var tP = make("span", "t");
    var sepP = make("span", "sep", "/");
    var mP = make("span", "m");
    chipP.appendChild(dotP);
    chipP.appendChild(tP);
    chipP.appendChild(sepP);
    chipP.appendChild(mP);

    var link = make("div", "route-link");
    link.setAttribute("aria-hidden", "true");

    var roleS = make("span", "role", "Secondary");
    var chipS = make("span", "chip chip-secondary");
    var dotS = make("span", "kdot");
    var tS = make("span", "t");
    var sepS = make("span", "sep", "/");
    var mS = make("span", "m");
    chipS.appendChild(dotS);
    chipS.appendChild(tS);
    chipS.appendChild(sepS);
    chipS.appendChild(mS);

    var note = make("p", "pc-note");

    var details = make("details", "more");
    var summary = make("summary", null, "available models");
    var list = make("ul");
    details.appendChild(summary);
    details.appendChild(list);
    details.hidden = true;

    route.appendChild(roleP);
    route.appendChild(chipP);
    route.appendChild(link);
    route.appendChild(roleS);
    route.appendChild(chipS);
    route.appendChild(note);

    card.appendChild(head);
    card.appendChild(route);

    var refs = {
      el: card,
      meta: meta,
      chipP: chipP, dotP: dotP, tP: tP, sepP: sepP, mP: mP,
      link: link,
      roleS: roleS, chipS: chipS, dotS: dotS, tS: tS, sepS: sepS, mS: mS,
      note: note,
      details: details, summary: summary, list: list,
      lastPrimary: null, lastSecondary: null, lastAvail: null
    };

    card.appendChild(buildPolicyEditor(refs, cap));
    card.appendChild(details);

    return refs;
  }

  function fillRouteChip(card, which, value) {
    var isPrimary = which === "primary";
    var chip = isPrimary ? card.chipP : card.chipS;
    var dot = isPrimary ? card.dotP : card.dotS;
    var t = isPrimary ? card.tP : card.tS;
    var sep = isPrimary ? card.sepP : card.sepS;
    var m = isPrimary ? card.mP : card.mS;

    if (!value) {
      chip.hidden = true;
      t.textContent = "";
      m.textContent = "";
      dot.style.background = "";
      return;
    }
    chip.hidden = false;
    var parts = splitRoute(value);
    setText(t, parts.target);
    setText(m, parts.model);
    sep.hidden = !parts.model;
    dot.style.background = kindColorFor(parts.target);
    chip.setAttribute(
      "title",
      (isPrimary ? "Primary: " : "Secondary: ") + (parts.entry || parts.target)
    );
  }

  /* ---------------------------------------------------------- activity -- */
  /* "Is this Tiiny working right now?" - answered by the appliance, not
     by the reservation. The reservation says who CLAIMED the box; the
     NPU telemetry says whether it is actually running something, and
     the sparkline shows the last few minutes so a box that was busy a
     minute ago does not read as idle. */

  var activityCards = new Map();

  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return "—";
    var s = Math.round(Number(seconds));
    if (s < 60) return s + "s";
    var m = Math.floor(s / 60);
    if (m < 60) return m + "m " + (s % 60) + "s";
    var h = Math.floor(m / 60);
    return h + "h " + (m % 60) + "m";
  }

  function stateLabel(state) {
    if (state === "busy") return "BUSY";
    if (state === "offline") return "OFFLINE";
    if (state === "idle") return "IDLE";
    return "UNKNOWN";
  }

  // A sparkline of the recent NPU load. Pure SVG, no dependencies, and
  // it keeps its stroke width even though the viewBox is stretched -
  // vector-effect does that, so the line stays 1.5px at any width.
  function buildSparkline(history) {
    var values = [];
    (history || []).forEach(function (h) {
      var u = h && h.u !== null && h.u !== undefined ? Number(h.u) : 0;
      if (isNaN(u)) u = 0;
      values.push(clamp(u, 0, 100));
    });

    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "spark");
    svg.setAttribute("viewBox", "0 0 100 30");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");

    // the baseline, so an empty chart still reads as a chart
    var base = document.createElementNS("http://www.w3.org/2000/svg", "line");
    base.setAttribute("x1", "0");
    base.setAttribute("x2", "100");
    base.setAttribute("y1", "29.5");
    base.setAttribute("y2", "29.5");
    base.setAttribute("class", "spark-base");
    svg.appendChild(base);

    if (!values.length) return svg;

    var step = values.length > 1 ? 100 / (values.length - 1) : 100;
    var points = values.map(function (v, i) {
      var x = values.length > 1 ? i * step : 100;
      var y = 29 - (v / 100) * 28;
      return x.toFixed(2) + "," + y.toFixed(2);
    }).join(" ");

    var area = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    area.setAttribute("points", "0,30 " + points + " 100,30");
    area.setAttribute("class", "spark-area");
    svg.appendChild(area);

    var line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("points", points);
    line.setAttribute("class", "spark-line");
    line.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(line);

    return svg;
  }

  function activityRow(label, value, cls) {
    var row = make("div", "act-row");
    row.appendChild(make("span", "act-k", label));
    row.appendChild(make("span", "act-v" + (cls ? " " + cls : ""), value));
    return row;
  }

  function buildActivityCard(entry) {
    var card = make("article", "card activity-card");
    card.setAttribute("data-state", entry.state || "unknown");

    var head = make("div", "card-head");
    var dot = make("span", "dot " + (entry.state || "unknown"));
    head.appendChild(dot);
    head.appendChild(make("h3", null, entry.target));
    var badge = make("span", "badge act-" + (entry.state || "unknown"),
                     stateLabel(entry.state));
    head.appendChild(badge);
    var pct = make("span", "lat");
    head.appendChild(pct);
    card.appendChild(head);

    // the load meter: compute utilisation, not memory
    var meter = make("div", "load-meter");
    var fill = make("div", "load-fill");
    meter.appendChild(fill);
    card.appendChild(meter);

    var spark = make("div", "spark-wrap");
    card.appendChild(spark);

    var detail = make("div", "act-detail");
    card.appendChild(detail);

    var tasks = make("div", "act-tasks");
    card.appendChild(tasks);

    var reserve = make("div", "act-reserve");
    card.appendChild(reserve);

    return {
      el: card, dot: dot, badge: badge, pct: pct, fill: fill, spark: spark,
      detail: detail, tasks: tasks, reserve: reserve,
      lastState: null, lastHist: null
    };
  }

  function renderActivity(data) {
    var grid = $("#activity-grid");
    if (!grid) return;
    var list = (data && data.targets) || [];
    var empty = $("#activity-empty");
    if (empty) empty.hidden = list.length > 0;

    var seen = {};
    list.forEach(function (entry) {
      if (!entry || !entry.target) return;
      seen[entry.target] = true;
      var card = activityCards.get(entry.target);
      if (!card) {
        card = buildActivityCard(entry);
        activityCards.set(entry.target, card);
        grid.appendChild(card.el);
      }
      updateActivityCard(card, entry);
    });

    activityCards.forEach(function (card, id) {
      if (!seen[id]) {
        card.el.remove();
        activityCards.delete(id);
      }
    });
  }

  function updateActivityCard(card, entry) {
    if (card.lastState !== entry.state) {
      card.lastState = entry.state;
      card.el.setAttribute("data-state", entry.state || "unknown");
      // the dot carries the state too - leaving it on the class it was
      // built with shows an amber dot beside a green IDLE badge
      card.dot.className = "dot " + (entry.state || "unknown");
      card.badge.className = "badge act-" + (entry.state || "unknown");
      setText(card.badge, stateLabel(entry.state));
    }

    var util = entry.util_percent;
    if (util === null || util === undefined || isNaN(util)) {
      setText(card.pct, "—");
      card.fill.style.width = "0%";
    } else {
      var p = clamp(Number(util), 0, 100);
      setText(card.pct, fmtPct(p) + " load");
      if (card.fill.style.width !== p + "%") card.fill.style.width = p + "%";
      var color = p >= 65 ? "var(--tm-warn, #f7b955)" : "var(--tm-ok, #3ddc97)";
      card.fill.style.setProperty("--meter-color", color);
    }

    // the sparkline only redraws when the series actually changed
    var hist = entry.history || [];
    var key = hist.length + ":" + (hist.length ? hist[hist.length - 1].t : 0);
    if (key !== card.lastHist) {
      card.lastHist = key;
      card.spark.textContent = "";
      card.spark.appendChild(buildSparkline(hist));
    }

    card.detail.textContent = "";
    var requests = entry.active_requests || 0;
    if (entry.state === "offline") {
      card.detail.appendChild(activityRow("state", entry.error || "unreachable", "warn"));
    } else {
      card.detail.appendChild(activityRow(
        "requests in flight", String(requests),
        requests > 0 ? "hot" : ""));
      var memUsed = fmtMb(entry.mem_used_mb);
      var memTotal = fmtMb(entry.mem_total_mb);
      if (memUsed) {
        card.detail.appendChild(activityRow(
          "NPU memory resident", memUsed + (memTotal ? " of " + memTotal : "")));
      }
      if (entry.busy_since) {
        card.detail.appendChild(activityRow(
          "busy for", fmtDuration((entry.sampled_at || 0) - entry.busy_since)));
      }
    }

    card.tasks.textContent = "";
    var taskList = entry.tasks || [];
    if (taskList.length) {
      card.tasks.appendChild(make("span", "act-k", "running now"));
      taskList.forEach(function (t) {
        var row = make("div", "act-task");
        row.appendChild(make("span", "act-task-model", t.model || "—"));
        var bits = [];
        if (t.modality) bits.push(t.modality);
        if (t.age_s !== null && t.age_s !== undefined) bits.push(fmtDuration(t.age_s));
        row.appendChild(make("span", "act-task-meta", bits.join(" · ")));
        card.tasks.appendChild(row);
      });
    }

    card.reserve.textContent = "";
    if (entry.held_by) {
      card.reserve.appendChild(make("span", "act-k", "reserved by"));
      card.reserve.appendChild(make("span", "act-v", entry.held_by));
      if ((entry.held_models || []).length) {
        card.reserve.appendChild(make("span", "act-desc", entry.held_models.join(", ")));
      }
    } else {
      card.reserve.appendChild(make("span", "act-k", "reserved by"));
      card.reserve.appendChild(make("span", "act-v dim", "nobody"));
    }
  }

  /* --------------------------------------------------------- policy edit -- */
  /* Each capability card gets a PRIMARY and a SECONDARY control. The
     choices are the targets in the mesh: picking one means "this target,
     whichever of its models serves the capability". A slot that already
     names a specific model keeps that model as its own choice, so saving
     an untouched card never silently changes which model serves it. */

  function slotChoices(cap, currentEntry) {
    var out = [];
    out.push({ value: "", label: "Not set", kind: null });
    var cur = splitRoute(currentEntry);
    targetOrder.forEach(function (id) {
      var t = targetInfo[id] || {};
      var label = id;
      var name = shortName(t);
      if (name && name !== id) label = id + " — " + name;
      var models = (modelsByCap[cap] || {})[id] || [];
      if (!models.length) {
        label += "  (no " + (CAP_LABEL[cap] || cap) + " model)";
      }
      out.push({ value: id, label: label, kind: kindFamily(t.kind) });
      // the model this slot names today, if it names one
      if (cur.entry && cur.target === id && cur.model && cur.entry !== id) {
        out.push({
          value: cur.entry,
          label: id + " — " + cur.model + "  (current)",
          kind: kindFamily(t.kind)
        });
      }
    });
    return out;
  }

  function fillSlotSelect(sel, choices, value) {
    sel.textContent = "";
    choices.forEach(function (c) {
      var opt = make("option", null, c.label);
      opt.value = c.value;
      sel.appendChild(opt);
    });
    sel.value = value;
    if (sel.value !== value) {
      // the value is not on the list any more (the target went away)
      var opt = make("option", null, value + "  (unavailable)");
      opt.value = value;
      sel.appendChild(opt);
      sel.value = value;
    }
  }

  // The line under a control: which target is chosen, what it is, and
  // how much it can do for this capability.
  function describeSlot(node, value, cap) {
    node.textContent = "";
    if (!value) {
      node.appendChild(make("span", "desc", "Not set — the mesh default serves this capability."));
      return;
    }
    var parts = splitRoute(value);
    var t = targetInfo[parts.target] || {};
    var badge = make("span", "badge k-" + kindFamily(t.kind), t.kind || "target");
    badge.setAttribute("title", "kind: " + (t.kind || "unknown"));
    node.appendChild(badge);
    node.appendChild(make("span", "tgt", parts.target));
    var name = shortName(t);
    if (name && name !== parts.target) node.appendChild(make("span", "desc", name));
    if (parts.model) {
      node.appendChild(make("span", "desc", "· " + parts.model));
    } else {
      var models = (modelsByCap[cap] || {})[parts.target] || [];
      if (models.length) {
        node.appendChild(
          make("span", "desc", "· " + models.length + " " + (CAP_LABEL[cap] || cap) + " models")
        );
      }
    }
  }

  function setPcStatus(card, text, kind) {
    if (!card.status) return;
    setText(card.status, text || "");
    card.status.className = "pc-status" + (kind ? " " + kind : "");
  }

  function markDirty(card) {
    if (!card) return;
    card.dirty = true;
    if (card.dirtyTag) card.dirtyTag.hidden = false;
    if (card.saveBtn) card.saveBtn.disabled = false;
  }

  function clearDirty(card) {
    if (!card) return;
    card.dirty = false;
    if (card.dirtyTag) card.dirtyTag.hidden = true;
    if (card.saveBtn) card.saveBtn.disabled = true;
  }

  function buildPolicyEditor(card, cap) {
    var edit = make("div", "pc-edit");

    var selPrimary = null;
    var selSecondary = null;
    var notePrimary = null;
    var noteSecondary = null;

    ["primary", "secondary"].forEach(function (slot) {
      var row = make("div", "pc-slot");
      row.setAttribute("data-slot", slot);
      row.appendChild(make("span", "pc-slot-label", slot === "primary" ? "Primary" : "Secondary"));
      var sel = make("select", "control");
      sel.setAttribute(
        "aria-label",
        (slot === "primary" ? "Primary" : "Secondary") + " target for " + (CAP_LABEL[cap] || cap)
      );
      row.appendChild(sel);
      var note = make("span", "pc-slot-note");
      row.appendChild(note);
      edit.appendChild(row);
      if (slot === "primary") {
        selPrimary = sel;
        notePrimary = note;
      } else {
        selSecondary = sel;
        noteSecondary = note;
      }
      sel.addEventListener("change", function () {
        card.pending[slot] = sel.value;
        markDirty(card);
        describeSlot(note, sel.value, cap);
        setPcStatus(card, "Not saved yet.", "");
      });
    });

    var actions = make("div", "pc-edit-actions");
    var save = make("button", "btn", "Save routing");
    save.type = "button";
    save.disabled = true;
    var dirty = make("span", "pc-dirty", "unsaved");
    dirty.hidden = true;
    var status = make("span", "pc-status");
    actions.appendChild(save);
    actions.appendChild(dirty);
    actions.appendChild(status);
    edit.appendChild(actions);

    card.saveBtn = save;
    card.dirtyTag = dirty;
    card.status = status;
    card.selPrimary = selPrimary;
    card.selSecondary = selSecondary;
    card.notePrimary = notePrimary;
    card.noteSecondary = noteSecondary;
    card.pending = { primary: null, secondary: null };
    card.cap = cap;

    save.addEventListener("click", function () {
      savePolicy(card, cap);
    });

    return edit;
  }

  function syncPolicyEditor(card, cap, entry) {
    if (!card.selPrimary) return;
    var cur = entry || {};
    var choicesP = slotChoices(cap, cur.primary);
    var choicesS = slotChoices(cap, cur.secondary);

    var valP = card.pending.primary !== null ? card.pending.primary : (splitRoute(cur.primary).entry || "");
    var valS = card.pending.secondary !== null ? card.pending.secondary : (splitRoute(cur.secondary).entry || "");

    // a pending choice that is no longer on the list stays on the list
    if (card.pending.primary !== null && !choicesP.some(function (c) { return c.value === card.pending.primary; })) {
      choicesP.push({ value: card.pending.primary, label: card.pending.primary, kind: null });
    }
    if (card.pending.secondary !== null && !choicesS.some(function (c) { return c.value === card.pending.secondary; })) {
      choicesS.push({ value: card.pending.secondary, label: card.pending.secondary, kind: null });
    }

    fillSlotSelect(card.selPrimary, choicesP, valP);
    fillSlotSelect(card.selSecondary, choicesS, valS);
    describeSlot(card.notePrimary, valP, cap);
    describeSlot(card.noteSecondary, valS, cap);
  }

  function savePolicy(card, cap) {
    var key = readKey();
    var primary = card.selPrimary.value;
    var secondary = card.selSecondary.value;

    if (!key) {
      setPcStatus(card, "The gateway needs its key before it will accept a change.", "err");
      revealKeyField();
      return;
    }

    card.saveBtn.disabled = true;
    setPcStatus(card, "Saving…", "");

    apiWrite("/mesh/policy", {
      capability: cap,
      // "" clears the slot; a target id means "this target, whichever of
      // its models serves the capability"
      primary: primary,
      secondary: secondary
    }).then(function (res) {
      if (!res.ok) {
        // keep the operator's selection: a rejected change must not
        // silently revert to what the server happened to hold
        markDirty(card);
        card.saveBtn.disabled = false;
        setPcStatus(card, res.error || "the gateway rejected the change", "err");
        return;
      }
      card.pending.primary = null;
      card.pending.secondary = null;
      clearDirty(card);
      setPcStatus(card, "Saved. The mesh reloaded it from the config file.", "ok");
      fetchMesh();
    }).catch(function (err) {
      card.saveBtn.disabled = false;
      markDirty(card);
      setPcStatus(card, describeError(err), "err");
    });
  }

  function renderPolicy(policy, capabilities) {
    var grid = $("#policy-grid");
    if (!grid) return;
    var data = policy || {};
    var caps = CAP_ORDER.slice();
    Object.keys(data).forEach(function (k) {
      if (caps.indexOf(k) === -1) caps.push(k);
    });
    Object.keys(capabilities || {}).forEach(function (k) {
      if (caps.indexOf(k) === -1) caps.push(k);
    });

    var seen = {};
    caps.forEach(function (cap) {
      var entry = data[cap] || {};
      var card = policyCards.get(cap);
      if (!card) {
        card = buildPolicyCard(cap);
        policyCards.set(cap, card);
        grid.appendChild(card.el);
      }
      seen[cap] = true;

      var primary = entry.primary || null;
      var secondary = entry.secondary || null;

      fillRouteChip(card, "primary", primary);
      fillRouteChip(card, "secondary", secondary);

      card.roleS.hidden = !secondary;
      card.chipS.hidden = !secondary;
      card.link.hidden = !secondary;

      if (!primary) {
        setText(card.note, "Not configured - requests for this capability fall back to the mesh default.");
      } else if (!secondary) {
        setText(card.note, "No secondary - if the primary goes down this capability has nowhere to fall back to.");
      } else {
        setText(card.note, "");
      }

      syncPolicyEditor(card, cap, entry);

      var capInfo = (capabilities || {})[cap] || null;
      var avail = capInfo && Array.isArray(capInfo.available) ? capInfo.available : [];
      setText(
        card.meta,
        avail.length ? avail.length + " available" : primary ? "configured" : ""
      );

      var availKey = avail.join("|");
      if (availKey !== card.lastAvail) {
        card.lastAvail = availKey;
        card.list.textContent = "";
        avail.forEach(function (id) {
          var li = make("li", null, id);
          li.title = id;
          card.list.appendChild(li);
        });
        setText(card.summary, avail.length ? avail.length + " available model" + (avail.length === 1 ? "" : "s") : "available models");
        card.details.hidden = avail.length === 0;
      }

      // the slots are objects now, so compare them by their entry - a
      // reference check would flash the chip on every poll
      var primaryKey = splitRoute(primary).entry;
      var secondaryKey = splitRoute(secondary).entry;
      if (card.lastPrimary !== primaryKey) {
        if (card.lastPrimary !== null) flash(card.chipP);
        card.lastPrimary = primaryKey;
      }
      if (card.lastSecondary !== secondaryKey) {
        if (card.lastSecondary !== null) flash(card.chipS);
        card.lastSecondary = secondaryKey;
      }
    });

    policyCards.forEach(function (card, cap) {
      if (!seen[cap]) {
        card.el.remove();
        policyCards.delete(cap);
      }
    });

    reorder(grid, Array.prototype.slice.call(caps).filter(function (c) {
      return policyCards.has(c);
    }).map(function (c) {
      return policyCards.get(c).el;
    }));
  }

  function buildTargetCard() {
    var card = make("article", "card target");

    var head = make("div", "card-head");
    var dot = make("span", "dot");
    var h3 = make("h3", "tname");
    var badge = make("span", "badge");
    var lat = make("span", "lat");
    head.appendChild(dot);
    head.appendChild(h3);
    head.appendChild(badge);
    head.appendChild(lat);

    var meter = make("div", "meter");
    var meterTop = make("div", "meter-top");
    // This meter is NPU MEMORY - how much of the pool resident models
    // have allocated. It is not a load meter: a box with a model loaded
    // and nothing running reads high here and is idle. The live load
    // lives in the Device activity panel.
    var meterLabel = make("span", null, "NPU memory");
    var meterVal = make("span", "meter-value");
    var meterStrong = make("b", null, "—");
    var meterOf = make("em", null, "");
    meterVal.appendChild(meterStrong);
    meterVal.appendChild(meterOf);
    meterTop.appendChild(meterLabel);
    meterTop.appendChild(meterVal);
    var bar = make("div", "meter-bar");
    var fill = make("div", "meter-fill");
    bar.appendChild(fill);
    meter.appendChild(meterTop);
    meter.appendChild(bar);

    var load = make("div", "tload");
    var loadDot = make("span", "dot");
    var loadText = make("span", null, "");
    load.appendChild(loadDot);
    load.appendChild(loadText);

    var stats = make("div", "target-stats");
    var models = make("span");
    var prio = make("span");
    stats.appendChild(models);
    stats.appendChild(prio);

    var roles = make("div", "chiprow roles");

    var caps = make("div", "chiprow");

    var resident = make("div", "resident");
    var resLabel = make("span", "res-label", "resident");
    resident.appendChild(resLabel);

    var note = make("p", "note");

    card.appendChild(head);
    card.appendChild(meter);
    card.appendChild(load);
    card.appendChild(stats);
    card.appendChild(roles);
    card.appendChild(caps);
    card.appendChild(resident);
    card.appendChild(note);

    return {
      el: card, dot: dot, name: h3, badge: badge, lat: lat,
      meter: meter, meterStrong: meterStrong, meterOf: meterOf, fill: fill,
      load: load, loadDot: loadDot, loadText: loadText,
      models: models, prio: prio, roles: roles, caps: caps,
      resident: resident, note: note,
      lastState: null, lastCaps: null, lastRes: null, lastRoles: null,
      lastLoad: null
    };
  }

  function renderTargets(targets, roles) {
    var grid = $("#target-grid");
    if (!grid) return;
    var list = Array.isArray(targets) ? targets.slice() : [];

    list.sort(function (a, b) {
      var pa = a && a.priority !== undefined && a.priority !== null ? a.priority : 999;
      var pb = b && b.priority !== undefined && b.priority !== null ? b.priority : 999;
      if (pa !== pb) return pa - pb;
      return String((a && a.id) || "").localeCompare(String((b && b.id) || ""));
    });

    kindByTarget = {};
    list.forEach(function (t) {
      if (t && t.id) kindByTarget[t.id] = kindFamily(t.kind);
    });

    var seen = {};
    list.forEach(function (t) {
      if (!t || !t.id) return;
      seen[t.id] = true;
      var card = targetCards.get(t.id);
      if (!card) {
        card = buildTargetCard();
        targetCards.set(t.id, card);
        grid.appendChild(card.el);
      }
      updateTargetCard(card, t, roles[t.id]);
    });

    targetCards.forEach(function (card, id) {
      if (!seen[id]) {
        card.el.remove();
        targetCards.delete(id);
      }
    });

    reorder(grid, list.filter(function (t) {
      return t && t.id && targetCards.has(t.id);
    }).map(function (t) {
      return targetCards.get(t.id).el;
    }));
  }

  function updateTargetCard(card, t, roles) {
    var st = healthState(t);
    card.el.setAttribute("data-state", st);
    if (card.lastState !== st) {
      card.dot.className = "dot " + st;
      card.lastState = st;
    }
    setText(card.name, t.id);
    setText(card.badge, t.kind ? String(t.kind) : "target");
    card.badge.className = "badge k-" + kindFamily(t.kind);
    card.badge.setAttribute("title", "kind: " + (t.kind || "unknown"));

    var latText = st === "down" && t.http ? "HTTP " + t.http : fmtMs(t.ms);
    if (card.lat.textContent !== latText) {
      setText(card.lat, latText);
    }

    // NPU meter - only for the appliances that report one.
    var pct = t.npu_used_percent;
    if (pct === undefined || pct === null || isNaN(pct)) {
      card.meter.hidden = true;
    } else {
      card.meter.hidden = false;
      var p = clamp(Number(pct), 0, 100);
      var total = fmtMb(t.npu_total_mb);
      setText(card.meterStrong, fmtPct(p));
      setText(card.meterOf, total ? "of " + total : "");
      var color = p >= 90 ? "var(--tm-down, #ff6f7d)" : p >= 65 ? "var(--tm-warn, #f7b955)" : "var(--tm-ok, #3ddc97)";
      card.fill.style.setProperty("--meter-color", color);
      if (card.fill.style.width !== p + "%") card.fill.style.width = p + "%";
    }

    // live load - the answer to "is this box working right now".
    // It comes from the activity sampler, not from the NPU memory meter
    // above: memory says how much is allocated, this says how much is
    // actually computing.
    var loadPct = t.npu_load_percent;
    var loadState = t.npu_state;
    var loadKey = loadState + ":" + loadPct + ":" + (t.active_requests || 0);
    if (loadKey !== card.lastLoad) {
      card.lastLoad = loadKey;
      if (loadState === "busy") {
        card.load.hidden = false;
        card.loadDot.className = "dot busy";
        setText(card.loadText,
          "busy" + (loadPct === undefined || loadPct === null
            ? "" : " · " + fmtPct(Number(loadPct)) + " NPU load") +
          (t.active_requests ? " · " + t.active_requests + " request" +
            (t.active_requests === 1 ? "" : "s") + " in flight" : ""));
      } else if (loadState === "offline") {
        card.load.hidden = false;
        card.loadDot.className = "dot down";
        setText(card.loadText, "unreachable");
      } else if (loadState === "idle") {
        card.load.hidden = false;
        card.loadDot.className = "dot up";
        setText(card.loadText, "idle" + (loadPct === undefined || loadPct === null
          ? "" : " · " + fmtPct(Number(loadPct)) + " NPU load"));
      } else {
        card.load.hidden = true;
      }
    }

    // model counts
    var served = t.models_served;
    var totalModels = t.models_total;
    if (served === undefined && totalModels === undefined) {
      setText(card.models, "");
    } else {
      setText(
        card.models,
        (served === undefined || served === null ? "?" : fmtInt(served)) +
          " resident · " +
          (totalModels === undefined || totalModels === null ? "?" : fmtInt(totalModels)) +
          " in store"
      );
    }
    setText(card.prio, t.priority === undefined || t.priority === null ? "" : "priority " + t.priority);

    // policy roles on this target
    var roleKey = roles
      ? roles.primary.join(",") + "|" + roles.secondary.join(",")
      : "";
    if (roleKey !== card.lastRoles) {
      card.lastRoles = roleKey;
      card.roles.textContent = "";
      if (roles) {
        roles.primary.forEach(function (cap) {
          card.roles.appendChild(roleBadge(cap, "primary"));
        });
        roles.secondary.forEach(function (cap) {
          card.roles.appendChild(roleBadge(cap, "secondary"));
        });
      }
    }

    // capabilities
    var capKey = Array.isArray(t.capabilities) ? t.capabilities.join(",") : "";
    if (capKey !== card.lastCaps) {
      card.lastCaps = capKey;
      card.caps.textContent = "";
      (t.capabilities || []).forEach(function (c) {
        card.caps.appendChild(make("span", "cap-chip", c));
      });
    }

    // resident models
    var resKey = Array.isArray(t.resident) ? t.resident.join("|") : "";
    if (resKey !== card.lastRes) {
      card.lastRes = resKey;
      var res = t.resident || [];
      card.resident.textContent = "";
      card.resident.appendChild(make("span", "res-label", "resident"));
      if (!res.length) {
        card.resident.appendChild(make("span", "res-model", "none loaded"));
      } else {
        res.slice(0, 3).forEach(function (m) {
          var chip = make("span", "res-model", m);
          chip.title = m;
          card.resident.appendChild(chip);
        });
        if (res.length > 3) {
          card.resident.appendChild(make("span", "res-model", "+" + (res.length - 3) + " more"));
        }
      }
    }

    setText(card.note, t.note || "");
  }

  function roleBadge(cap, role) {
    var b = make("span", "role-badge " + (role === "primary" ? "p" : "s"));
    b.appendChild(make("span", "sr-only", role === "primary" ? "primary for " : "secondary for "));
    b.appendChild(make("span", null, (role === "primary" ? "▲ " : "▽ ") + cap));
    b.title = (role === "primary" ? "primary" : "secondary") + " for " + cap;
    return b;
  }

  // Keep DOM order in sync with the data order, but only when it actually
  // changed - moving nodes around loses keyboard focus.
  function reorder(parent, ordered) {
    var current = Array.prototype.slice.call(parent.children);
    var same = current.length === ordered.length;
    if (same) {
      for (var i = 0; i < ordered.length; i++) {
        if (current[i] !== ordered[i]) {
          same = false;
          break;
        }
      }
    }
    if (same) return;
    ordered.forEach(function (node) {
      parent.appendChild(node);
    });
  }

  function renderTotals(totals, targets, policy) {
    var t = totals || {};
    var list = targets || [];
    var up = 0;
    list.forEach(function (x) {
      if (healthState(x) === "up") up++;
    });
    var targetCount = t.targets !== undefined && t.targets !== null ? t.targets : list.length;
    var upCount = t.up !== undefined && t.up !== null ? t.up : up;
    var models = t.models;
    if (models === undefined || models === null) {
      models = list.reduce(function (sum, x) {
        return sum + (Number(x && x.models_total) || 0);
      }, 0);
    }
    var chatRoutable = t.chat_routable;

    var upStat = $("#stat-up");
    if (upStat) {
      setText(upStat.querySelector(".v .n"), fmtInt(upCount));
      setText(upStat.querySelector(".v .of"), " / " + fmtInt(targetCount));
      upStat.classList.toggle("good", targetCount > 0 && upCount === targetCount);
      upStat.classList.toggle("warn", targetCount > 0 && upCount < targetCount);
    }
    setText($("#stat-models .v .n"), fmtInt(models));
    setText(
      $("#stat-chat .v .n"),
      chatRoutable === undefined || chatRoutable === null ? "—" : fmtInt(chatRoutable)
    );
    // how many capabilities have a primary route. The gateway counts them;
    // fall back to counting the policy ourselves if it does not say.
    var routed = t.capabilities_routed;
    if (routed === undefined || routed === null) {
      routed = (policy || {}).length;
      Object.keys(policy || {}).forEach(function (cap) {
        var entry = (policy || {})[cap] || {};
        if (entry.primary) routed++;
      });
    }
    setText($("#stat-caps .v .n"), fmtInt(routed));
    var capsStat = $("#stat-caps");
    if (capsStat) {
      var withFallback = t.capabilities_with_fallback;
      capsStat.setAttribute(
        "title",
        withFallback === undefined || withFallback === null
          ? "capabilities with a primary route"
          : fmtInt(routed) + " with a primary route, " + fmtInt(withFallback) + " with a fallback"
      );
    }
  }

  /* ---------------------------------------------------------- background -- */

  function applyBackground(theme) {
    var path = backgroundPath(theme && theme.background_url ? theme.background_url : "");
    paintBackground(path);
    updateBackgroundPreview(path);
  }

  function applyAccent(theme) {
    var accent = theme && theme.accent ? String(theme.accent).trim() : "";
    if (!accent) return;
    if (!/^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(accent)) return;
    document.documentElement.style.setProperty("--tm-accent", accent);
  }

  /* ---------------------------------------------------------------- key -- */
  /* The write routes need the gateway's key. It is never printed and
     never written to a file - it lives in this browser's localStorage
     and travels as a bearer header. It can also be handed over in the
     page URL as ?key=..., which is then taken out of the address bar. */

  function readKey() {
    try {
      return localStorage.getItem(KEY_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function writeKey(value) {
    try {
      if (value) localStorage.setItem(KEY_KEY, value);
      else localStorage.removeItem(KEY_KEY);
    } catch (e) {
      /* private mode - the key simply will not persist */
    }
  }

  // A key handed over in the URL is a convenience for the first visit:
  // pick it up, keep it, and scrub it from the address bar so it does
  // not linger in history or in a screenshot.
  function takeKeyFromUrl() {
    try {
      var m = /[?&]key=([^&#]*)/.exec(location.search);
      if (!m) return "";
      var value = decodeURIComponent(m[1] || "");
      if (value) writeKey(value);
      try {
        var clean = location.pathname + location.hash;
        history.replaceState(null, "", clean);
      } catch (e) {
        /* history is not ours to rewrite - the key still works */
      }
      return value;
    } catch (e) {
      return "";
    }
  }

  function authHeaders() {
    var headers = { Accept: "application/json" };
    var key = readKey();
    if (key) headers["Authorization"] = "Bearer " + key;
    return headers;
  }

  /* ---------------------------------------------------------- appearance -- */
  /* The appearance area is built by script: the page is a single inlined
     file, and the section is new, so there is no static markup to edit. */

  var bgBust = 0;         // cache-buster, so a fresh upload is not the old file
  var bgAppliedPath = ""; // the path currently painted on the bg layer

  // The gateway reports the background as an absolute loopback URL; the
  // page paints it from its own origin instead, so the two agree and the
  // background does not flicker on every poll.
  function backgroundPath(url) {
    if (!url) return "";
    var s = String(url);
    var i = s.indexOf("/ui/background");
    if (i !== -1) return s.slice(i);
    var j = s.indexOf("://");
    if (j !== -1) {
      var slash = s.indexOf("/", j + 3);
      return slash === -1 ? "" : s.slice(slash);
    }
    return s.charAt(0) === "/" ? s : "";
  }

  function backgroundSrc(path) {
    if (!path) return "";
    return path + (bgBust ? "?v=" + bgBust : "");
  }

  function paintBackground(path) {
    var layer = $(".bg-layer");
    if (!layer) return;
    if (!path) {
      layer.style.backgroundImage = "";
      layer.classList.add("bg-fallback");
      bgAppliedPath = "";
      return;
    }
    var src = backgroundSrc(path);
    if (src === bgAppliedPath) return;
    var img = new Image();
    img.onload = function () {
      if (bgAppliedPath !== src) return;
      layer.style.backgroundImage = 'url("' + src.replace(/"/g, "%22") + '")';
      layer.classList.remove("bg-fallback");
    };
    img.onerror = function () {
      if (bgAppliedPath !== src) return;
      layer.style.backgroundImage = "";
      layer.classList.add("bg-fallback");
    };
    bgAppliedPath = src;
    layer.classList.add("bg-fallback");
    img.src = src;
  }

  function setApStatus(text, kind) {
    var node = $("#ap-status");
    if (!node) return;
    setText(node, text || "");
    node.className = "pc-status" + (kind ? " " + kind : "");
  }

  function updateBackgroundPreview(path) {
    var preview = $("#ap-preview");
    if (!preview) return;
    if (path) {
      preview.style.backgroundImage = 'url("' + backgroundSrc(path).replace(/"/g, "%22") + '")';
      preview.classList.remove("empty");
      setText(preview, "");
    } else {
      preview.style.backgroundImage = "";
      preview.classList.add("empty");
      setText(preview, "No background image set.");
    }
    var rm = $("#ap-remove");
    if (rm) rm.disabled = !path;
  }

  function uploadBackground(file) {
    if (!file) return;
    if (BG_TYPES.indexOf(file.type) === -1) {
      setApStatus("That is not a png, jpeg, webp or gif - the gateway only takes those.", "err");
      return;
    }
    if (file.size > MAX_BG_BYTES) {
      setApStatus(
        "That image is " + fmtMb(file.size / 1048576) + " MB - the limit is 12 MB.",
        "err"
      );
      return;
    }
    if (!readKey()) {
      setApStatus("The gateway needs its key before it will accept an upload.", "err");
      revealKeyField();
      return;
    }

    var headers = { "Content-Type": file.type };
    var key = readKey();
    if (key) headers["Authorization"] = "Bearer " + key;

    setApStatus("Uploading…", "");
    fetch(API_BASE + "/ui/background", {
      method: "POST",
      headers: headers,
      body: file
    }).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (e) {
          data = null;
        }
        if (!res.ok) {
          setApStatus((data && data.error) || ("the gateway answered HTTP " + res.status), "err");
          return null;
        }
        return data;
      });
    }).then(function (data) {
      if (!data) return;
      bgBust = Date.now();
      var path = backgroundPath(data.background_url || "/ui/background");
      paintBackground(path);
      updateBackgroundPreview(path);
      setApStatus("Background updated.", "ok");
    }).catch(function (err) {
      setApStatus(describeError(err), "err");
    });
  }

  function removeBackground() {
    if (!readKey()) {
      setApStatus("The gateway needs its key before it will accept a removal.", "err");
      revealKeyField();
      return;
    }
    setApStatus("Removing…", "");
    apiDelete("/ui/background").then(function (res) {
      if (!res.ok) {
        setApStatus(res.error || "the gateway rejected the removal", "err");
        return;
      }
      bgBust = Date.now();
      paintBackground("");
      updateBackgroundPreview("");
      setApStatus("Background removed.", "ok");
    }).catch(function (err) {
      setApStatus(describeError(err), "err");
    });
  }

  function revealKeyField() {
    var field = $("#ap-key");
    if (!field) return;
    var section = $("#appearance");
    if (section) {
      section.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    try {
      field.focus({ preventScroll: true });
    } catch (e) {
      field.focus();
    }
  }

  function buildAppearance() {
    var section = make("section", "section");
    section.id = "appearance";
    section.setAttribute("aria-labelledby", "h-appearance");

    var head = make("div", "section-head");
    var h2 = make("h2", null, "Appearance");
    h2.id = "h-appearance";
    head.appendChild(h2);
    head.appendChild(make("span", "hint", "theme, background image and the gateway key"));
    section.appendChild(head);

    var grid = make("div", "ap-grid");

    /* -- background image ------------------------------------------- */
    var bgCard = make("div", "card ap-card");
    bgCard.appendChild(make("h3", null, "Background image"));
    bgCard.appendChild(
      make(
        "p",
        "ap-sub",
        "A png, jpeg, webp or gif, up to 12 MB. It sits behind the whole page, under a veil so the text stays readable."
      )
    );

    var preview = make("div", "ap-preview empty");
    preview.id = "ap-preview";
    preview.setAttribute("role", "img");
    preview.setAttribute("aria-label", "current background image");
    bgCard.appendChild(preview);

    var row = make("div", "ap-row");
    var file = make("input", "control");
    file.type = "file";
    file.id = "ap-file";
    file.accept = "image/png,image/jpeg,image/webp,image/gif";
    file.addEventListener("change", function () {
      var f = file.files && file.files[0];
      uploadBackground(f);
      // allow the same file to be picked again
      try {
        file.value = "";
      } catch (e) {
        /* some browsers refuse to reset it - harmless */
      }
    });
    row.appendChild(file);

    var remove = make("button", "btn", "Remove");
    remove.type = "button";
    remove.id = "ap-remove";
    remove.disabled = true;
    remove.addEventListener("click", removeBackground);
    row.appendChild(remove);
    bgCard.appendChild(row);

    bgCard.appendChild(make("p", "ap-note", "The image is stored on the gateway and survives a restart."));
    grid.appendChild(bgCard);

    /* -- gateway key ------------------------------------------------ */
    var keyCard = make("div", "card ap-card");
    keyCard.appendChild(make("h3", null, "Gateway key"));
    keyCard.appendChild(
      make(
        "p",
        "ap-sub",
        "Reading the dashboard needs no key. Changing the routing policy or the background does."
      )
    );

    var keyRow = make("div", "ap-key-row");
    var keyField = make("input", "control");
    keyField.type = "password";
    keyField.id = "ap-key";
    keyField.placeholder = "paste the gateway key";
    keyField.autocomplete = "off";
    keyField.spellcheck = false;
    keyRow.appendChild(keyField);

    var keySave = make("button", "btn", "Save key");
    keySave.type = "button";
    keySave.addEventListener("click", function () {
      var value = keyField.value.trim();
      writeKey(value);
      keyField.value = "";
      setApStatus(
        value ? "Key saved in this browser." : "Key cleared.",
        value ? "ok" : ""
      );
    });
    keyRow.appendChild(keySave);
    keyCard.appendChild(keyRow);

    keyCard.appendChild(
      make(
        "p",
        "ap-note",
        "It stays in this browser's local storage and is sent as a bearer header. You can also open the page once with ?key=… and the dashboard will keep it."
      )
    );
    grid.appendChild(keyCard);

    section.appendChild(grid);

    var status = make("p", "pc-status");
    status.id = "ap-status";
    section.appendChild(status);

    return section;
  }

  /* --------------------------------------------------------------- api -- */

  function describeError(err) {
    if (!err) return "unknown error";
    if (err.name === "AbortError") {
      return "the request timed out after " + Math.round(REQUEST_TIMEOUT_MS / 1000) + "s";
    }
    if (err.name === "TypeError") {
      return "the gateway refused the connection (it may be down, or blocking this origin)";
    }
    return err.message || String(err);
  }

  // A write that speaks JSON. Resolves with {ok, error} - the server's
  // own error text is kept, because it says what was actually wrong.
  function apiWrite(path, body) {
    var headers = authHeaders();
    headers["Content-Type"] = "application/json";
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, REQUEST_TIMEOUT_MS) : null;
    var opts = { method: "POST", headers: headers, body: JSON.stringify(body) };
    if (ctrl) opts.signal = ctrl.signal;

    return fetch(API_BASE + path, opts).then(function (res) {
      if (timer) clearTimeout(timer);
      return res.text().then(function (text) {
        var data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (e) {
          data = null;
        }
        if (!res.ok) {
          return {
            ok: false,
            status: res.status,
            error: (data && data.error) || ("the gateway answered HTTP " + res.status)
          };
        }
        return { ok: true, status: res.status, data: data };
      });
    });
  }

  function apiDelete(path) {
    var headers = authHeaders();
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, REQUEST_TIMEOUT_MS) : null;
    var opts = { method: "DELETE", headers: headers };
    if (ctrl) opts.signal = ctrl.signal;

    return fetch(API_BASE + path, opts).then(function (res) {
      if (timer) clearTimeout(timer);
      return res.text().then(function (text) {
        var data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (e) {
          data = null;
        }
        if (!res.ok) {
          return {
            ok: false,
            status: res.status,
            error: (data && data.error) || ("the gateway answered HTTP " + res.status)
          };
        }
        return { ok: true, status: res.status, data: data };
      });
    });
  }

  function fetchMesh() {
    if (state.loading) return;
    state.loading = true;
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, REQUEST_TIMEOUT_MS) : null;

    var opts = { cache: "no-store", headers: { Accept: "application/json" } };
    if (ctrl) opts.signal = ctrl.signal;

    fetch(API_BASE + "/mesh/ui", opts)
      .then(function (res) {
        if (timer) clearTimeout(timer);
        if (!res.ok) throw new Error("the gateway answered HTTP " + res.status + " " + (res.statusText || ""));
        return res.text();
      })
      .then(function (text) {
        var data;
        try {
          data = JSON.parse(text);
        } catch (e) {
          throw new Error("the gateway did not return JSON (got " + text.slice(0, 80).replace(/\s+/g, " ") + ")");
        }
        if (!data || typeof data !== "object") throw new Error("unexpected payload from the gateway");
        state.data = data;
        state.error = null;
        state.lastOk = Date.now();
        clearError();
        renderAll(data);
        setConnection("live");
      })
      .catch(function (err) {
        state.error = err;
        setConnection("down", err);
        renderError(err);
      })
      .then(function () {
        state.loading = false;
        scheduleNext();
      });
  }

  function scheduleNext() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(function () {
      if (document.hidden) {
        // idle while the tab is hidden; resume immediately when it returns
        scheduleNext();
        return;
      }
      fetchMesh();
    }, POLL_MS);
  }

  var pollTimer = null;
  var activityTimer = null;

  /* The activity poll is separate from the main one on purpose: it is
     small, it is about a different question, and it must not be blocked
     by a slow /mesh/ui (which probes every appliance and can take
     seconds on a cold start). */
  function fetchActivity() {
    fetch(API_BASE + "/mesh/activity", { cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        renderActivity(data);
      })
      .catch(function (err) {
        // The panel keeps whatever it last knew; a failed activity poll
        // must not blank the section or raise a banner.
        var empty = $("#activity-empty");
        if (empty && !activityCards.size) {
          empty.hidden = false;
          empty.textContent = "The gateway did not report device activity: " + describeError(err);
        }
      })
      .then(function () {
        clearTimeout(activityTimer);
        activityTimer = setTimeout(fetchActivity, ACTIVITY_POLL_MS);
      });
  }

  /* ---------------------------------------------------------- rendering -- */

  function renderAMC(amcData) {
    var grid = $("#amc-grid");
    if (!grid) return;
    grid.innerHTML = "";
    var subsystems = (amcData && amcData.subsystems) || [];
    var empty = $("#amc-empty");
    if (empty) empty.hidden = subsystems.length > 0;

    subsystems.forEach(function (s) {
      var card = make("div", "amc-card");
      var head = make("div", "card-head");
      var dot = make("span", "dot " + (s.state || "unknown"));
      var h3 = make("h3", "", s.label || s.id);
      head.appendChild(dot);
      head.appendChild(h3);
      card.appendChild(head);

      if (s.role) {
        card.appendChild(make("div", "amc-role", s.role));
      }
      if (s.summary) {
        card.appendChild(make("div", "amc-summary", s.summary));
      }

      var details = make("div", "amc-details");
      if (s.detail) {
        Object.keys(s.detail).forEach(function (k) {
          var val = s.detail[k];
          if (val !== null && val !== undefined) {
            var row = make("div", "", k + ": " + (typeof val === "object" ? JSON.stringify(val) : String(val)));
            details.appendChild(row);
          }
        });
      }
      if (s.error) {
        var errRow = make("div", "e-detail", "Error: " + s.error);
        errRow.style.color = "var(--tm-down, #ff6f7d)";
        details.appendChild(errRow);
      }
      card.appendChild(details);
      grid.appendChild(card);
    });
  }

  function renderCredits(creditsData) {
    var container = $("#credits-container");
    if (!container) return;
    container.innerHTML = "";
    if (!creditsData) return;

    var card = make("div", "credits-card");
    var head = make("div", "card-head");
    head.appendChild(make("h3", "", "OpenRouter Balance"));
    card.appendChild(head);

    if (creditsData.ok) {
      if (creditsData.scope === "account") {
        var balText = creditsData.balance !== null ? "$" + Number(creditsData.balance).toFixed(2) : "--";
        card.appendChild(make("div", "credits-balance", balText));
        var used = creditsData.total_usage !== null ? "$" + Number(creditsData.total_usage).toFixed(2) : "--";
        var total = creditsData.total_credits !== null ? "$" + Number(creditsData.total_credits).toFixed(2) : "--";
        card.appendChild(make("div", "credits-detail", "Used " + used + " of " + total + " total purchased credits"));
      } else if (creditsData.scope === "key") {
        var remText = creditsData.limit_remaining !== null ? "$" + Number(creditsData.limit_remaining).toFixed(2) : "No cap set";
        card.appendChild(make("div", "credits-balance", remText));
        var kused = creditsData.key_usage !== null ? "$" + Number(creditsData.key_usage).toFixed(2) : "--";
        card.appendChild(make("div", "credits-detail", "Key spend: " + kused + " (limit remaining: " + remText + ")"));
        card.appendChild(make("div", "credits-note", "Showing per-key usage (OPENROUTER_API_KEY). Set OPENROUTER_MANAGEMENT_KEY for account-wide credit balance."));
      }
    } else {
      card.appendChild(make("div", "credits-balance", "--"));
      card.appendChild(make("div", "credits-detail", creditsData.error || "No credit data available"));
    }

    var actions = make("div", "credits-actions");
    var updated = make("span", "hint", "Updated: " + (creditsData.fetched_at ? fmtTime(creditsData.fetched_at) : "never"));
    var btn = make("button", "btn", "Refresh Credits ↻");
    btn.type = "button";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      setText(btn, "Refreshing...");
      fetch(API_BASE + "/mesh/openrouter/credits?refresh=1", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          renderCredits(data);
        })
        .catch(function (err) {
          console.error("Credits refresh failed", err);
          btn.disabled = false;
          setText(btn, "Refresh Credits ↻");
        });
    });

    actions.appendChild(btn);
    actions.appendChild(updated);
    card.appendChild(actions);
    container.appendChild(card);
  }

  function formatRemainingTime(sec) {
    if (sec === null || sec === undefined || sec <= 0) return "resets shortly";
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    if (h > 0) return "resets in " + h + "h " + m + "m";
    return "resets in " + m + "m";
  }

  function renderMiniMaxQuota(quotaData) {
    var container = $("#minimax-quota-container");
    if (!container) return;
    container.innerHTML = "";
    if (!quotaData) return;

    var card = make("div", "credits-card");
    var head = make("div", "card-head");
    var dot = make("span", "dot " + (quotaData.is_exhausted ? "down" : "up"));
    var h3 = make("h3", "", "MiniMax Token Plan");
    var badge = make("span", "badge " + (quotaData.is_exhausted ? "down" : "up"),
                     quotaData.is_exhausted ? "Quota Exhausted" : "Active (Annual Plan)");

    head.appendChild(dot);
    head.appendChild(h3);
    head.appendChild(badge);
    card.appendChild(head);

    if (quotaData.ok) {
      // 5-hour rolling interval meter
      var intWrap = make("div", "quota-meter-wrap");
      var intHead = make("div", "quota-meter-head");
      intHead.appendChild(make("span", "", "5-Hour Rolling Window"));
      var intPct = quotaData.interval_remaining_percent !== null ? quotaData.interval_remaining_percent : 100;
      intHead.appendChild(make("strong", "", fmtPct(intPct) + " remaining"));
      var intBar = make("div", "quota-bar");
      var intFill = make("div", "quota-fill" + (intPct <= 10 ? " exhausted" : intPct <= 25 ? " warn" : ""));
      intFill.style.width = clamp(intPct, 0, 100) + "%";
      intBar.appendChild(intFill);
      intWrap.appendChild(intHead);
      intWrap.appendChild(intBar);
      card.appendChild(intWrap);

      // Weekly quota meter
      var wkWrap = make("div", "quota-meter-wrap");
      var wkHead = make("div", "quota-meter-head");
      wkHead.appendChild(make("span", "", "Weekly Quota Window"));
      var wkPct = quotaData.weekly_remaining_percent !== null ? quotaData.weekly_remaining_percent : 0;
      wkHead.appendChild(make("strong", "", fmtPct(wkPct) + " remaining (" + formatRemainingTime(quotaData.weekly_remains_time_s) + ")"));
      var wkBar = make("div", "quota-bar");
      var wkFill = make("div", "quota-fill" + (wkPct <= 10 ? " exhausted" : wkPct <= 25 ? " warn" : ""));
      wkFill.style.width = clamp(wkPct, 0, 100) + "%";
      wkBar.appendChild(wkFill);
      wkWrap.appendChild(wkHead);
      wkWrap.appendChild(wkBar);
      card.appendChild(wkWrap);

      if (quotaData.is_exhausted) {
        card.appendChild(make("div", "credits-note", "Weekly quota limit reached. Auto-failover is active: all mesh chat requests transparently route to OpenRouter Gemini 3.8 Flash without stalling."));
      } else {
        card.appendChild(make("div", "credits-detail", "Primary cloud model active. Will automatically failover to OpenRouter Gemini if rate-limited."));
      }
    } else {
      card.appendChild(make("div", "credits-detail", quotaData.error || "Unable to read MiniMax quota"));
    }

    var actions = make("div", "credits-actions");
    var updated = make("span", "hint", "Updated: " + (quotaData.fetched_at ? fmtTime(quotaData.fetched_at) : "never"));
    var btn = make("button", "btn", "Refresh Quota ↻");
    btn.type = "button";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      setText(btn, "Refreshing...");
      fetch(API_BASE + "/mesh/minimax/quota?refresh=1", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          renderMiniMaxQuota(data);
        })
        .catch(function (err) {
          console.error("Quota refresh failed", err);
          btn.disabled = false;
          setText(btn, "Refresh Quota ↻");
        });
    });

    actions.appendChild(btn);
    actions.appendChild(updated);
    card.appendChild(actions);
    container.appendChild(card);
  }

  function updateFallbackButtons(activeTarget) {
    var btnOr = $("#fb-btn-or");
    var btnMm = $("#fb-btn-mm");
    if (btnOr) {
      if (activeTarget === "openrouter") btnOr.classList.add("active");
      else btnOr.classList.remove("active");
    }
    if (btnMm) {
      if (activeTarget === "minimax") btnMm.classList.add("active");
      else btnMm.classList.remove("active");
    }
  }

  function switchFallback(targetChoice) {
    var status = $("#fb-status");
    if (status) setText(status, "Switching to " + targetChoice + "…");
    apiWrite("/mesh/fallback", { target: targetChoice }).then(function (res) {
      if (!res.ok) {
        if (status) setText(status, "Error: " + (res.error || "switch failed"));
        return;
      }
      var label = targetChoice === "openrouter" ? "OpenRouter Gemini" : "MiniMax M3.1";
      if (status) setText(status, "Fallback active: " + label);
      updateFallbackButtons(targetChoice);
      fetchMesh();
    }).catch(function (err) {
      if (status) setText(status, "Error: " + describeError(err));
    });
  }

  var fbInitialized = false;
  function renderFallbackToggle(fbData) {
    var curr = (fbData && fbData.current) || "other";
    updateFallbackButtons(curr);
    var status = $("#fb-status");
    if (status && (!status.textContent || !status.textContent.trim())) {
      var label = curr === "openrouter" ? "OpenRouter Gemini" : curr === "minimax" ? "MiniMax M3.1" : (curr || "custom");
      setText(status, "Active: " + label);
    }
    if (!fbInitialized) {
      fbInitialized = true;
      var btnOr = $("#fb-btn-or");
      if (btnOr) {
        btnOr.addEventListener("click", function () { switchFallback("openrouter"); });
      }
      var btnMm = $("#fb-btn-mm");
      if (btnMm) {
        btnMm.addEventListener("click", function () { switchFallback("minimax"); });
      }
    }
  }

  function renderAll(data) {
    var theme = data.theme || {};
    applyAccent(theme);
    applyBackground(theme);

    var policy = data.policy || {};
    var capabilities = data.capabilities || {};
    var targets = data.targets || [];

    kindByTarget = {};
    targets.forEach(function (t) {
      if (t && t.id) kindByTarget[t.id] = kindFamily(t.kind);
    });
    indexTargets(targets);
    indexModels(capabilities);

    renderTotals(data.totals, targets, policy);
    renderPolicy(policy, capabilities);
    renderFallbackToggle(data.cloud_fallback);
    renderTargets(targets, computeRoles(policy));
    renderAMC(data.amc);
    renderMiniMaxQuota(data.minimax_quota);
    renderCredits(data.openrouter_credits);

    setText($("#snap-time"), fmtTime(data.generated));
    setText($("#snap-age"), state.lastOk ? "snapshot " + fmtTime(data.generated) : "");

    var empty = $("#policy-empty");
    if (empty) empty.hidden = Object.keys(policy).length > 0;
    var tEmpty = $("#target-empty");
    if (tEmpty) tEmpty.hidden = targets.length > 0;
  }

  function setConnection(mode, err) {
    var pill = $("#conn");
    if (!pill) return;
    pill.setAttribute("data-state", mode);
    setText($("#conn-text"), mode === "live" ? "live" : mode === "down" ? "unreachable" : "connecting");
    pill.setAttribute(
      "title",
      mode === "live" ? "connected to " + API_BASE : mode === "down" ? describeError(err) : "contacting the gateway"
    );
  }

  function renderError(err) {
    var banner = $("#banner");
    var reason = describeError(err);
    if (banner) {
      banner.hidden = false;
      setText($("#banner-title"), state.data ? "Lost the gateway" : "Cannot reach the TiinyMesh gateway");
      setText(
        $("#banner-detail"),
        (state.data ? "Showing the last known state. " : "") +
          reason +
          " (" + API_BASE + ")"
      );
    }
    if (!state.data) {
      var grid = $("#target-grid");
      if (grid && !grid.querySelector(".empty.err")) {
        var box = make("div", "empty err");
        box.setAttribute("role", "alert");
        box.appendChild(make("p", "e-title", "Cannot reach the TiinyMesh gateway"));
        box.appendChild(make("p", "e-detail", reason + " - tried " + API_BASE + "/mesh/ui"));
        var btn = make("button", "btn", "Retry");
        btn.type = "button";
        btn.addEventListener("click", function () {
          fetchMesh();
        });
        box.appendChild(btn);
        grid.appendChild(box);
      }
    }
  }

  function clearError() {
    var banner = $("#banner");
    if (banner) banner.hidden = true;
    var box = $("#target-grid .empty.err");
    if (box) box.remove();
  }

  /* ------------------------------------------------------------- clock -- */

  function tickClock() {
    var now = new Date();
    var timeEl = $("#clock-time");
    if (timeEl) {
      setText(
        timeEl,
        now.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false
        })
      );
    }
    var dateEl = $("#clock-date");
    if (dateEl) {
      setText(
        dateEl,
        now.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })
      );
    }
    var dt = $("#clock");
    if (dt) dt.setAttribute("datetime", now.toISOString());

    var age = $("#updated-age");
    if (age) {
      if (!state.lastOk) {
        setText(age, "never");
      } else {
        var s = Math.round((Date.now() - state.lastOk) / 1000);
        setText(age, s <= 1 ? "just now" : s + "s ago");
      }
    }
  }

  /* -------------------------------------------------------------- boot -- */

  function boot() {
    var html = document.documentElement;

    // Embedded or standalone? The Hermes preview frame injects --foreground.
    var embedded = isEmbedded();
    html.classList.toggle("embedded", embedded);
    html.classList.toggle("standalone", !embedded);

    // A key handed over in the URL is taken once and scrubbed from the
    // address bar, so a first visit can start editing right away.
    var urlKey = takeKeyFromUrl();

    var detected = detectMode();
    applyMode(detected.mode, detected.source);

    setText($("#api-endpoint"), API_BASE + "/mesh/ui");

    buildThemeControl();

    // The appearance section goes last in the main flow, after the targets.
    var main = $("main");
    if (main) main.appendChild(buildAppearance());

    var retry = $("#retry");
    if (retry) {
      retry.addEventListener("click", function () {
        fetchMesh();
      });
    }

    var refresh = $("#refresh");
    if (refresh) {
      refresh.addEventListener("click", function () {
        fetchMesh();
      });
    }

    tickClock();
    setInterval(tickClock, 1000);
    setConnection("wait");
    fetchMesh();
    // The activity panel polls on its own clock - it is a different
    // question at a different rate.
    fetchActivity();

    if (urlKey) {
      setApStatus("Key taken from the address bar and kept in this browser.", "ok");
    }

    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) {
        clearTimeout(pollTimer);
        fetchMesh();
      }
    });

    // The frame may inject its variables a moment after we booted; re-check.
    setTimeout(function () {
      var nowEmbedded = isEmbedded();
      if (nowEmbedded !== embedded) {
        html.classList.toggle("embedded", nowEmbedded);
        html.classList.toggle("standalone", !nowEmbedded);
        var d = detectMode();
        applyMode(d.mode, d.source);
      }
    }, 400);

    window.addEventListener("load", function () {
      var nowEmbedded = isEmbedded();
      if (nowEmbedded !== embedded) {
        html.classList.toggle("embedded", nowEmbedded);
        html.classList.toggle("standalone", !nowEmbedded);
        var d = detectMode();
        applyMode(d.mode, d.source);
      }
    });

    // The OS preference is the default only; an explicit choice wins.
    // "system" is an explicit choice too, but it means "follow the OS" -
    // so a change in the OS still moves the page.
    try {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () {
        var stored = readStoredTheme();
        if (!stored || stored === "system") {
          var d = detectMode();
          applyMode(d.mode, d.source);
        }
      };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    } catch (e) {
      /* no matchMedia - fine */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  // Expose a tiny surface for debugging / tests.
  window.TiinyMeshDashboard = {
    apiBase: API_BASE,
    reload: function () {
      fetchMesh();
    },
    state: state
  };
})();
