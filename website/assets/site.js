/* ZTako V3 — shared interactions (en + zh-CN).
   All strings and demo data live in each page's data-* JSON; no network calls.
   Engines: hero loop, task-zone demo player with confirm/cancel,
   background engine simulation, screenshot scenario demo, reveal. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function $(s, r) { return (r || document).querySelector(s); }
  function $all(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function parse(el, attr) { return JSON.parse(el.getAttribute(attr)); }

  /* ---------- Reveal ---------- */
  if ("IntersectionObserver" in window && !reduced) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { threshold: 0.1 });
    $all(".reveal").forEach(function (el) { io.observe(el); });
  } else {
    $all(".reveal").forEach(function (el) { el.classList.add("in"); });
  }

  var STEP_MS = 1150;

  /* ---------- Generic stage player ----------
     root provides: .stage-rail (li), .bubble-area (optional), .ms-track (optional i's),
     .ms-label (optional), .action-sheet + .sheet-backdrop (optional),
     .demo-status (optional line). Config from data-demo JSON:
     { stages: [{ label, bubbles: [{cls, text}] }], confirmAt: n|null,
       confirm: { title, rows: [[label, value]...], body }, msgs: { cancelled, confirmed } }
  */
  function makePlayer(root, cfg, onDone) {
    var rails = $all(".stage-rail li", root);
    var bubbleArea = $(".bubble-area", root);
    var track = $all(".ms-track i", root);
    var msLabel = $(".ms-label", root);
    var sheet = $(".action-sheet", root);
    var backdrop = $(".sheet-backdrop", root);
    var status = $(".demo-status", root);
    var timer = null, idx = 0, aborted = false;

    function clearAll() {
      rails.forEach(function (li) { li.classList.remove("active", "done", "cancelled"); });
      track.forEach(function (i) { i.classList.remove("on", "ok"); });
      if (bubbleArea) bubbleArea.innerHTML = "";
      if (sheet) sheet.classList.remove("show");
      if (backdrop) backdrop.classList.remove("show");
      if (msLabel) msLabel.textContent = "";
      if (status) { status.textContent = ""; status.classList.remove("ok", "stop"); }
    }
    function addBubbles(st) {
      if (!bubbleArea || !st.bubbles) return;
      st.bubbles.forEach(function (b) {
        var d = document.createElement("div");
        d.className = "bubble " + (b.cls === "user" ? "user" : "ai");
        d.textContent = b.text;
        bubbleArea.appendChild(d);
        requestAnimationFrame(function () { requestAnimationFrame(function () { d.classList.add("show"); }); });
      });
    }
    function showSheet() {
      if (!sheet) return;
      var c = cfg.confirm || {};
      var t = $("h4", sheet); if (t && c.title) t.textContent = c.title;
      var rows = $(".as-rows", sheet);
      if (rows && c.rows) {
        rows.innerHTML = "";
        c.rows.forEach(function (r) {
          var p = document.createElement("p"); p.className = "as-row";
          var b = document.createElement("b"); b.textContent = r[0] + " ";
          p.appendChild(b); p.appendChild(document.createTextNode(r[1]));
          rows.appendChild(p);
        });
      }
      var body = $(".as-body", sheet); if (body && c.body) body.textContent = c.body;
      if (backdrop) backdrop.classList.add("show");
      sheet.classList.add("show");
    }
    function hideSheet() {
      if (sheet) sheet.classList.remove("show");
      if (backdrop) backdrop.classList.remove("show");
    }
    function step(i) {
      if (aborted) return;
      if (i > 0) {
        rails[i - 1].classList.remove("active"); rails[i - 1].classList.add("done");
        if (track[i - 1]) { track[i - 1].classList.remove("on"); track[i - 1].classList.add("ok"); }
      }
      if (i >= cfg.stages.length) {
        if (msLabel) msLabel.textContent = "";
        if (onDone) onDone("done");
        return;
      }
      idx = i;
      var st = cfg.stages[i];
      rails[i].classList.add("active");
      if (track[i]) track[i].classList.add("on");
      addBubbles(st);
      if (msLabel) msLabel.textContent = st.label;
      if (cfg.confirmAt === i) {
        showSheet();
        return; // wait for user decision
      }
      timer = setTimeout(function () { step(i + 1); }, reduced ? 80 : STEP_MS);
    }
    return {
      start: function () {
        clearTimeout(timer); aborted = false; clearAll();
        timer = setTimeout(function () { step(0); }, reduced ? 80 : 500);
      },
      confirm: function () {
        hideSheet();
        timer = setTimeout(function () { step(idx + 1); }, reduced ? 80 : 500);
      },
      cancel: function () {
        hideSheet();
        aborted = true; clearTimeout(timer);
        rails[idx].classList.remove("active");
        rails[idx].classList.add("cancelled");
        for (var k = idx + 1; k < rails.length; k++) rails[k].style.opacity = "0.3";
        if (status) { status.textContent = (cfg.msgs && cfg.msgs.cancelled) || ""; status.classList.add("stop"); }
        if (onDone) onDone("cancelled");
      },
      reset: function () {
        clearTimeout(timer); aborted = false;
        rails.forEach(function (r) { r.style.opacity = ""; });
        clearAll();
      }
    };
  }

  function wireSheet(root, player) {
    var c = $(".as-confirm", root), x = $(".as-cancel", root);
    if (c) c.addEventListener("click", function () { player.confirm(); });
    if (x) x.addEventListener("click", function () { player.cancel(); });
  }

  /* ---------- SECTION 1: hero auto-loop ---------- */
  var hero = $("#heroDemo");
  if (hero) {
    var hcfg = parse(hero, "data-demo");
    var hPlayer = makePlayer(hero, hcfg, function (state) {
      if (state === "done") {
        timer = setTimeout(function () { hPlayer.start(); }, reduced ? 200 : 3600);
      }
    });
    var timer;
    wireSheet(hero, hPlayer);
    hPlayer.start();
  }

  /* ---------- SECTION 2: task zone ---------- */
  var zone = $("#taskZone");
  if (zone) {
    var tasks = parse(zone, "data-tasks");
    var menu = $all(".task-menu button", zone);
    var goalEl = $(".task-goal-text", zone);
    var railEl = $(".goal-steps .stage-rail", zone);
    var player = null, currentKey = null;
    var zoneRoot = $(".demo-root", zone);

    function renderTask(key) {
      var t = tasks[key];
      if (!t) return;
      currentKey = key;
      menu.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-task") === key ? "true" : "false"); });
      goalEl.innerHTML = "<span class='quote'>“</span>" + t.goal + "<span class='quote'>”</span>";
      railEl.innerHTML = "";
      t.stages.forEach(function (s) {
        var li = document.createElement("li");
        var d = document.createElement("span"); d.className = "dot";
        li.appendChild(d); li.appendChild(document.createTextNode(s.label));
        railEl.appendChild(li);
      });
      var msTrack = $(".ms-track", zoneRoot);
      if (msTrack) {
        msTrack.innerHTML = "";
        t.stages.forEach(function () { msTrack.appendChild(document.createElement("i")); });
      }
      if (player) player.reset();
      var cfg = { stages: t.stages, confirmAt: (typeof t.confirmAt === "number" ? t.confirmAt : null),
        confirm: t.confirm, msgs: tasks._msgs || {} };
      player = makePlayer(zoneRoot, cfg, null);
      wireSheet(zoneRoot, player);
      player.start();
    }
    menu.forEach(function (b) {
      b.addEventListener("click", function () {
        var k = b.getAttribute("data-task");
        if (k === "screenshot") {
          var anchor = $("#screenshot");
          if (anchor) anchor.scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
          return;
        }
        renderTask(k);
      });
    });
    var restart = $(".restart-btn", zone);
    if (restart) restart.addEventListener("click", function () { if (currentKey) renderTask(currentKey); });
    renderTask(Object.keys(tasks).filter(function (k) { return k[0] !== "_"; })[0]);
  }

  /* ---------- SECTION 3: background engine ---------- */
  var engine = $("#bgEngine");
  if (engine) {
    var ecfg = parse(engine, "data-demo");
    var stages = $all(".engine-stages .stage-chip", engine);
    var eStatus = $(".engine-status", engine);
    var eSpin = $(".spin", eStatus);
    var ePlayer = null, eTimer = null, eAborted = false;
    var eSheet = $(".action-sheet", engine);
    var eBackdrop = $(".sheet-backdrop", engine);

    function eShowSheet() {
      var c = ecfg.confirm || {};
      var rows = $(".as-rows", eSheet);
      if (rows && c.rows) { rows.innerHTML = ""; c.rows.forEach(function (r) {
        var p = document.createElement("p"); p.className = "as-row";
        var b = document.createElement("b"); b.textContent = r[0] + " ";
        p.appendChild(b); p.appendChild(document.createTextNode(r[1])); rows.appendChild(p);
      }); }
      var body = $(".as-body", eSheet); if (body && c.body) body.textContent = c.body;
      eBackdrop.classList.add("show"); eSheet.classList.add("show");
    }
    function eHideSheet() { eSheet.classList.remove("show"); eBackdrop.classList.remove("show"); }
    function eRun() {
      clearTimeout(eTimer); eAborted = false;
      stages.forEach(function (s) { s.classList.remove("active", "done"); });
      eHideSheet();
      eStatus.classList.remove("ok", "stop");
      eStatus.childNodes[eStatus.childNodes.length - 1].textContent = ecfg.msgs.working;
      var i = 0;
      (function next() {
        if (eAborted) return;
        if (i > 0) { stages[i - 1].classList.remove("active"); stages[i - 1].classList.add("done"); }
        if (i >= stages.length) {
          eShowSheet();
          eStatus.childNodes[eStatus.childNodes.length - 1].textContent = ecfg.msgs.needsApproval;
          return;
        }
        stages[i].classList.add("active");
        i++;
        eTimer = setTimeout(next, reduced ? 80 : 1400);
      })();
    }
    $(".engine-start", engine).addEventListener("click", eRun);
    $(".as-confirm", engine).addEventListener("click", function () {
      eHideSheet(); clearTimeout(eTimer);
      stages.forEach(function (s) { s.classList.remove("active"); s.classList.add("done"); });
      eStatus.classList.add("ok");
      eStatus.childNodes[eStatus.childNodes.length - 1].textContent = ecfg.msgs.confirmed;
    });
    $(".as-cancel", engine).addEventListener("click", function () {
      eHideSheet(); eAborted = true; clearTimeout(eTimer);
      stages.forEach(function (s) { s.classList.remove("active"); });
      eStatus.classList.add("stop");
      eStatus.childNodes[eStatus.childNodes.length - 1].textContent = ecfg.msgs.cancelled;
    });
  }

  /* ---------- SECTION 5: screenshot demo ---------- */
  var shot = $("#shotDemo");
  if (shot) {
    var scen = parse(shot, "data-scenarios");
    var tabs = $all(".shot-tabs button", shot);
    var frames = $all(".shot-frame", shot);
    var chips = $all(".shot-panel .stage-chip", shot);
    var out = $(".shot-output", shot);
    var actionBtns = $all(".shot-actions button", shot);
    var current = Object.keys(scen)[0];
    var analyzing = false;

    function setScenario(key) {
      current = key;
      var titleEl = $("#shotScenarioTitle");
      if (titleEl && scen[key].title) titleEl.textContent = scen[key].title;
      tabs.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-sc") === key ? "true" : "false"); });
      frames.forEach(function (f) { f.hidden = f.getAttribute("data-frame") !== key; });
      out.textContent = scen[key].intro;
      chips.forEach(function (c) { c.classList.remove("active"); });
      actionBtns.forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
    }
    tabs.forEach(function (b) { b.addEventListener("click", function () { setScenario(b.getAttribute("data-sc")); }); });
    var runBtn = $(".shot-run", shot);
    function runAnalysis() {
      if (analyzing) return;
      analyzing = true;
      var s = scen[current];
      out.textContent = s.running;
      chips.forEach(function (c) { c.classList.remove("active"); });
      var frame = frames.filter(function (f) { return !f.hidden; })[0];
      var regions = $all(".region", frame);
      regions.forEach(function (r) { r.classList.remove("on"); });
      var i = 0;
      (function next() {
        if (i > 0) chips[i - 1].classList.remove("active");
        if (i >= chips.length) {
          out.textContent = s.actions.analyze;
          analyzing = false;
          return;
        }
        chips[i].classList.add("active");
        if (regions[i]) regions[i].classList.add("on");
        i++;
        setTimeout(next, reduced ? 70 : 850);
      })();
    }
    if (runBtn) runBtn.addEventListener("click", runAnalysis);
    actionBtns.forEach(function (b) {
      b.addEventListener("click", function () {
        actionBtns.forEach(function (x) { x.setAttribute("aria-pressed", "false"); });
        b.setAttribute("aria-pressed", "true");
        var s = scen[current];
        out.textContent = s.actions[b.getAttribute("data-act")] || "";
      });
    });
    setScenario(current);
  }

  /* ---------- Footer year ---------- */
  $all("[data-year]").forEach(function (el) { el.textContent = String(new Date().getFullYear()); });
})();
