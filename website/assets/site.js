/* ZTako showcase — shared interactions (en + zh-CN).
   All demo data lives in each page's inline JSON; no network calls. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ---------- Scroll reveal ---------- */
  if ("IntersectionObserver" in window && !reduced) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12 });
    $all(".reveal").forEach(function (el) { io.observe(el); });
  } else {
    $all(".reveal").forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------- Hero: typing task + agent status chips ---------- */
  var taskEl = $("#heroTask");
  if (taskEl) {
    var tasks = JSON.parse(taskEl.getAttribute("data-tasks"));
    var chips = $all("#heroChips .chip");
    var caret = $(".caret", taskEl.parentNode);
    var ti = 0;

    function typeTask(text, done) {
      var i = 0;
      taskEl.textContent = "";
      if (reduced) { taskEl.textContent = text; done(); return; }
      (function tick() {
        taskEl.textContent = text.slice(0, ++i);
        if (i < text.length) { setTimeout(tick, 42); } else { done(); }
      })();
    }

    function runChips(done) {
      chips.forEach(function (c) { c.classList.remove("active", "done"); });
      if (reduced) {
        chips.forEach(function (c) { c.classList.add("done"); });
        done(); return;
      }
      var ci = 0;
      (function next() {
        if (ci > 0) chips[ci - 1].classList.replace("active", "done");
        if (ci >= chips.length) { done(); return; }
        chips[ci].classList.add("active");
        ci++;
        setTimeout(next, 850);
      })();
    }

    function loop() {
      chips.forEach(function (c) { c.classList.remove("active", "done"); });
      typeTask(tasks[ti % tasks.length], function () {
        setTimeout(function () {
          runChips(function () {
            ti++;
            setTimeout(loop, 1400);
          });
        }, reduced ? 300 : 600);
      });
    }
    loop();
  }

  /* ---------- Section 03: agent pipeline ---------- */
  var pipeline = $("#pipeline");
  if (pipeline) {
    var steps = $all(".step", pipeline);
    var pi = 0;
    function markStep(idx) {
      steps.forEach(function (s, i) {
        s.classList.toggle("active", i === idx);
        s.classList.toggle("done", i < idx);
        s.setAttribute("aria-pressed", i === idx ? "true" : "false");
      });
    }
    steps.forEach(function (s, i) {
      s.addEventListener("click", function () { pi = i; markStep(i); });
      s.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pi = i; markStep(i); }
      });
    });
    if (!reduced) {
      setInterval(function () {
        pi = (pi + 1) % steps.length;
        markStep(pi);
      }, 1600);
    } else {
      markStep(0);
    }
  }

  /* ---------- Section 05: link phase label ---------- */
  var linkLabel = $("#linkLabel");
  if (linkLabel && !reduced) {
    var phases = JSON.parse(linkLabel.getAttribute("data-phases"));
    var pni = 0;
    setInterval(function () {
      pni = (pni + 1) % phases.length;
      linkLabel.innerHTML = "<b>" + phases[pni][0] + "</b>" + phases[pni][1];
    }, 2600);
  }

  /* ---------- Section 06: keyboard demo ---------- */
  var kbTyped = $("#kbTyped");
  if (kbTyped) {
    $all("#kbCands .cand").forEach(function (btn) {
      btn.addEventListener("click", function () {
        kbTyped.textContent = btn.getAttribute("data-text");
        var note = $("#kbNote");
        if (note) note.textContent = btn.getAttribute("data-note") || "";
      });
    });
    $all("#kbActs .act").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var note = $("#kbNote");
        if (note) note.textContent = btn.getAttribute("data-note") || "";
      });
    });
  }

  /* ---------- Section 07: vision demo ---------- */
  var vision = $("#visionDemo");
  if (vision) {
    var stages = $all("#visionStages .stage-chip");
    var regions = $all("#shot .region");
    var output = $("#visionOutput");
    var modes = $all("#visionModes button");
    var modeData = JSON.parse(vision.getAttribute("data-modes"));
    var currentMode = "analyze";
    var analyzing = false;

    function setOutput(key) {
      if (output && modeData[key]) output.textContent = modeData[key];
    }
    modes.forEach(function (btn) {
      btn.addEventListener("click", function () {
        modes.forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
        btn.setAttribute("aria-pressed", "true");
        currentMode = btn.getAttribute("data-mode");
        setOutput(currentMode);
        stages.forEach(function (s) { s.classList.remove("active"); });
        regions.forEach(function (r) { r.classList.remove("on"); });
      });
    });

    var analyzeBtn = $("#analyzeBtn");
    if (analyzeBtn) {
      analyzeBtn.addEventListener("click", function () {
        if (analyzing) return;
        analyzing = true;
        setOutput("running");
        stages.forEach(function (s) { s.classList.remove("active"); });
        regions.forEach(function (r) { r.classList.remove("on"); });
        var si = 0;
        (function nextStage() {
          if (si > 0) stages[si - 1].classList.remove("active");
          if (si >= stages.length) {
            if (modeData[currentMode]) setOutput(currentMode);
            analyzing = false;
            return;
          }
          stages[si].classList.add("active");
          var region = regions[si];
          if (region && !reduced) region.classList.add("on");
          if (region && reduced) region.classList.add("on");
          si++;
          setTimeout(nextStage, reduced ? 60 : 900);
        })();
      });
    }
  }

  /* ---------- Section 08: local/cloud toggle ---------- */
  var modelToggle = $("#modelToggle");
  if (modelToggle) {
    var tbtns = $all("button", modelToggle);
    tbtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        tbtns.forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
        btn.setAttribute("aria-pressed", "true");
        var target = btn.getAttribute("data-panel");
        $all(".model-card").forEach(function (card) {
          card.hidden = card.getAttribute("data-card") !== target;
        });
      });
    });
  }

  /* ---------- Footer year ---------- */
  $all("[data-year]").forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });
})();
