/* Edge AI Stress Sense - diagrams, charts, navigation. No dependencies. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const $ = (s) => document.querySelector(s);
  const el = (tag, attrs = {}, parent, text) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  };

  /* ------------------------------------------------------------ theme */
  const root = document.documentElement;
  try { const t = localStorage.getItem("theme"); if (t) root.dataset.theme = t; } catch (e) { /* storage blocked */ }
  const qt = new URLSearchParams(location.search).get("theme");
  if (qt === "dark" || qt === "light") root.dataset.theme = qt;
  $("#themeBtn").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) { /* ignore */ }
  });

  /* ------------------------------------------------------------ scrollspy */
  const links = [...document.querySelectorAll("#navLinks a")];
  const spy = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (!en.isIntersecting) return;
      links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + en.target.id));
      const act = links.find((a) => a.classList.contains("active"));
      if (act) act.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
  }, { rootMargin: "-45% 0px -50% 0px" });
  document.querySelectorAll("section[id]").forEach((s) => spy.observe(s));

  /* ------------------------------------------------------------ tooltip */
  const tip = $("#tip");
  const showTip = (html, ev) => {
    tip.innerHTML = html;
    tip.classList.remove("hidden");
    const w = tip.offsetWidth;
    tip.style.left = Math.min(ev.clientX + 14, innerWidth - w - 8) + "px";
    tip.style.top = ev.clientY + 14 + "px";
  };
  const hideTip = () => tip.classList.add("hidden");

  function defs(svg) {
    const d = el("defs", {}, svg);
    for (const [id, cls] of [["arr", "dg-arrow"], ["arrW", "dg-arrow wifi"], ["arrD", "dg-arrow data"]]) {
      const m = el("marker", { id: svg.id + id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, d);
      el("path", { d: "M0 0 L10 5 L0 10 z", class: cls }, m);
    }
  }

  /* ------------------------------------------------------------ architecture */
  (function arch() {
    const svg = $("#archDiagram");
    defs(svg);
    const N = {
      mic: [20, 30, 165, 56, "INMP441 mic", "I2S · 16 kHz"],
      mpu: [20, 110, 165, 56, "MPU6050", "accelerometer · 32 Hz"],
      esp32: [250, 40, 185, 120, "ESP32", "mic + motion · coordinator", true],
      ppg: [20, 250, 165, 56, "PPG pulse sensor", "analog"],
      gsr: [20, 330, 165, 56, "Grove GSR", "analog"],
      ads: [222, 282, 128, 74, "ADS1115", "16-bit ADC · I2C"],
      esp8266: [400, 262, 180, 112, "ESP8266", "64 Hz sampling", true],
      led: [222, 384, 128, 52, "LED", "while collecting"],
      laptop: [655, 110, 180, 230, "Laptop server", "", true],
      dash: [868, 120, 122, 56, "Dashboard", "browser :8080"],
      spk: [868, 250, 122, 56, "Speaker", "spoken result"],
    };
    const anchor = (id, side, dy = 0) => {
      const [x, y, w, h] = N[id];
      return { l: [x, y + h / 2 + dy], r: [x + w, y + h / 2 + dy], t: [x + w / 2, y], b: [x + w / 2, y + h] }[side];
    };
    const W = [
      ["mic", "r", "esp32", "l", 0, -25], ["mpu", "r", "esp32", "l", 0, 25],
      ["ppg", "r", "ads", "l", 0, -15], ["gsr", "r", "ads", "l", 0, 15], ["ads", "r", "esp8266", "l", 0, 0],
      ["esp8266", "b", "led", "r", 0, 0, false, true],
      ["esp32", "b", "esp8266", "t", 0, 0, true, false, "START · ACK · heartbeat (UDP)", [300, 215]],
      ["esp32", "r", "laptop", "l", -20, -60, true, false, "WebSocket: audio, status, commands", [445, 62]],
      ["esp32", "r", "laptop", "l", 30, -5, true, false, "UDP: motion 32 Hz", [445, 150]],
      ["esp8266", "r", "laptop", "l", 0, 70, true, false, "UDP: pulse + skin 64 Hz", [592, 392]],
      ["laptop", "r", "dash", "l", -80, 0], ["laptop", "r", "spk", "l", 50, 0],
    ];
    const gW = el("g", {}, svg), gN = el("g", {}, svg);
    W.forEach(([a, sa, b, sb, d1, d2, wifi, rev, label, lp]) => {
      let [x1, y1] = anchor(a, sa, sa === "l" || sa === "r" ? d1 : 0);
      let [x2, y2] = anchor(b, sb, sb === "l" || sb === "r" ? d2 : 0);
      const horiz = sa === "l" || sa === "r";
      let d;
      if (rev) d = `M${x1} ${y1} V${y2} H${x2}`;
      else if (horiz) { const m = (x2 - x1) / 2; d = `M${x1} ${y1} C${x1 + m} ${y1} ${x2 - m} ${y2} ${x2} ${y2}`; }
      else { const m = (y2 - y1) / 2; d = `M${x1} ${y1} C${x1} ${y1 + m} ${x2} ${y2 - m} ${x2} ${y2}`; }
      el("path", { d, class: "dg-wire" + (wifi ? " wifi" : ""), "marker-end": `url(#${svg.id}${wifi ? "arrW" : "arr"})` }, gW);
      if (label) el("text", { x: lp[0], y: lp[1], class: "dg-label" }, gW, label);
    });
    for (const [id, [x, y, w, h, t, s, hl]] of Object.entries(N)) {
      el("rect", { x, y, width: w, height: h, rx: 10, class: "dg-box" + (hl ? " hl" : "") }, gN);
      el("text", { x: x + 12, y: y + 23, class: "dg-title" }, gN, t);
      if (s) el("text", { x: x + 12, y: y + 41, class: "dg-sub" }, gN, s);
      if (id === "laptop") ["speech-to-text", "command matching", "device hub + loss stats", "feature extraction", "stress model", "text-to-speech"]
        .forEach((line, i) => el("text", { x: x + 14, y: y + 52 + i * 26, class: "dg-label" }, gN, "▸ " + line));
      if (id === "led") el("circle", { cx: x + w - 18, cy: y + 18, r: 7, fill: "#ffcc33" }, gN);
    }
  })();

  /* ------------------------------------------------------------ sequence */
  (function seq() {
    const svg = $("#seqDiagram");
    defs(svg);
    const L = { you: [90, "You"], e32: [340, "ESP32"], e86: [590, "ESP8266"], lap: [860, "Laptop"] };
    const top = 20, bottom = 545;
    for (const [, [x, name]] of Object.entries(L)) {
      el("line", { x1: x, y1: top + 34, x2: x, y2: bottom, class: "dg-life" }, svg);
      el("rect", { x: x - 60, y: top, width: 120, height: 34, rx: 8, class: "dg-box hl" }, svg);
      el("text", { x, y: top + 22, class: "dg-title", "text-anchor": "middle" }, svg, name);
    }
    // [from, to, y, label, kind]
    const M = [
      ["you", "e32", 90, "“measure my stress level”", ""],
      ["e32", "lap", 125, "speech audio (WebSocket, 16 kHz)", ""],
      ["lap", "lap", 155, "speech-to-text → command = measure", "self"],
      ["lap", "e32", 200, "measure_start {id, 60 000 ms}", ""],
      ["e32", "e86", 240, "UDP START, id, 60 000, laptop IP (retry every 250 ms)", ""],
      ["e86", "e32", 275, "ACK, id", "ack"],
      ["e32", "lap", 305, "peer_event: ack", "ack"],
      ["e86", "e86", 335, "LED on, sampling", "self"],
      ["e86", "lap", 375, "PPG + GSR @ 64 Hz (UDP 4211)", "data"],
      ["e32", "lap", 410, "MPU6050 @ 32 Hz (UDP 4213)", "data"],
      ["e86", "e32", 450, "DONE after 60 s, LED off", ""],
      ["lap", "lap", 480, "features → model → result", "self"],
      ["lap", "you", 525, "spoken result + dashboard", ""],
    ];
    el("rect", { x: 580, y: 330, width: 20, height: 125, class: "dg-act" }, svg);
    M.forEach(([a, b, y, label, kind]) => {
      const x1 = L[a][0], x2 = L[b][0];
      if (kind === "self") {
        const bx = Math.max(5, Math.min(x1 - 150, 995 - 300));
        el("rect", { x: bx, y: y - 15, width: 300, height: 26, rx: 6, class: "dg-box" }, svg);
        el("text", { x: bx + 150, y: y + 3, class: "dg-label", "text-anchor": "middle" }, svg, label);
        return;
      }
      const dir = x2 > x1 ? 1 : -1;
      el("line", { x1: x1 + dir * 4, y1: y, x2: x2 - dir * 6, y2: y, class: "dg-msg " + kind,
        "marker-end": `url(#${svg.id}${kind === "data" ? "arrD" : "arr"})` }, svg);
      el("text", { x: (x1 + x2) / 2, y: y - 7, class: "dg-label", "text-anchor": "middle" }, svg, label);
    });
  })();

  /* ------------------------------------------------------------ results data (from tools/ml/models/benchmark.json) */
  const SETS = [["acc", "Motion"], ["bvp", "Pulse"], ["eda", "Skin"], ["physio", "Pulse + skin"], ["all", "All sensors"]];
  const R = {"binary|abs|bvp":["LDA",90.2,88.4],"binary|abs|eda":["LDA",85.4,82.4],"binary|abs|acc":["RF",87.5,85.0],"binary|abs|physio":["LDA",91.2,89.6],"binary|abs|all":["LDA",94.3,93.3],"binary|rel|bvp":["AB",87.9,85.8],"binary|rel|eda":["LDA",88.9,86.1],"binary|rel|acc":["AB",81.7,77.9],"binary|rel|physio":["AB",94.7,93.8],"binary|rel|all":["AB",94.9,94.1],"3class|abs|bvp":["AB",67.1,58.1],"3class|abs|eda":["kNN",66.7,56.6],"3class|abs|acc":["RF",74.9,67.0],"3class|abs|physio":["kNN",69.5,59.1],"3class|abs|all":["LDA",77.3,66.7],"3class|rel|bvp":["RF",71.0,58.9],"3class|rel|eda":["RF",74.0,62.4],"3class|rel|acc":["AB",65.2,57.7],"3class|rel|physio":["AB",74.8,65.4],"3class|rel|all":["AB",76.1,69.9]};
  // WESAD paper, Tables 3/4, wrist device, best accuracy per modality (physio/all include TEMP)
  const PAPER = { binary: { acc: 71.7, bvp: 85.8, eda: 79.7, physio: 88.3, all: 87.1 },
                  "3class": { acc: 57.2, bvp: 70.2, eda: 62.3, physio: 76.2, all: 75.2 } };
  const CLF = { AB: "AdaBoost", LDA: "Linear discriminant analysis", RF: "Random forest", kNN: "k-nearest neighbours", DT: "Decision tree" };

  function accChart(task) {
    const host = $("#accChart");
    host.innerHTML = "";
    const W = 900, H = 330, pad = { l: 44, r: 10, t: 22, b: 40 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Accuracy by sensor set" }, host);
    const Y = (v) => pad.t + (1 - v / 100) * (H - pad.t - pad.b);
    [0, 25, 50, 75, 100].forEach((v) => {
      el("line", { x1: pad.l, x2: W - pad.r, y1: Y(v), y2: Y(v), class: v ? "gridline" : "baseline" }, svg);
      el("text", { x: pad.l - 8, y: Y(v) + 4, "text-anchor": "end" }, svg, v + "%");
    });
    const gw = (W - pad.l - pad.r) / SETS.length, bw = Math.min(56, gw * 0.3);
    const g = el("g", {}, svg);
    SETS.forEach(([key, name], i) => {
      const cx = pad.l + gw * i + gw / 2;
      [["abs", "--series-1", -1], ["rel", "--series-2", 1]].forEach(([norm, color, side]) => {
        const [clf, acc, f1] = R[`${task}|${norm}|${key}`];
        const x = cx + side * (bw / 2 + 1) - bw / 2, y = Y(acc), h = Y(0) - y;
        const r = 4;
        const bar = el("path", { class: "bar", fill: `var(${color})`,
          d: `M${x} ${Y(0)} V${y + r} Q${x} ${y} ${x + r} ${y} H${x + bw - r} Q${x + bw} ${y} ${x + bw} ${y + r} V${Y(0)} Z` }, g);
        el("text", { x: x + bw / 2, y: y - 6, "text-anchor": "middle", class: "val" }, g, acc.toFixed(1));
        const html = `<div class="k">${name} · ${norm === "rel" ? "with personal baseline" : "raw features"}</div>
          <div>accuracy <b>${acc.toFixed(1)} %</b> · macro-F1 <b>${f1.toFixed(1)} %</b></div>
          <div class="k">${CLF[clf]} · paper: ${PAPER[task][key].toFixed(1)} %</div>`;
        const hit = el("rect", { x: x - 2, y: pad.t, width: bw + 4, height: Y(0) - pad.t, fill: "transparent" }, g);
        hit.addEventListener("mousemove", (ev) => { g.classList.add("dim"); bar.classList.add("on"); showTip(html, ev); });
        hit.addEventListener("mouseleave", () => { g.classList.remove("dim"); bar.classList.remove("on"); hideTip(); });
      });
      const py = Y(PAPER[task][key]);
      el("line", { x1: cx - bw - 8, x2: cx + bw + 8, y1: py, y2: py, stroke: "var(--text-primary)", "stroke-width": 2 }, svg);
      el("text", { x: cx, y: H - pad.b + 20, "text-anchor": "middle", style: "fill:var(--text-secondary);font-size:13px" }, svg, name);
    });
    $("#accTitle").textContent = task === "binary" ? "Stress vs. no stress: accuracy by sensor set"
                                                   : "Baseline / stress / amusement: accuracy by sensor set";
    // table view
    const rows = SETS.map(([k, n]) => {
      const a = R[`${task}|abs|${k}`], b = R[`${task}|rel|${k}`];
      return `<tr><td>${n}</td><td>${a[0]}</td><td class="num">${a[1].toFixed(1)}</td><td class="num">${a[2].toFixed(1)}</td>
        <td>${b[0]}</td><td class="num">${b[1].toFixed(1)}</td><td class="num">${b[2].toFixed(1)}</td><td class="num">${PAPER[task][k].toFixed(1)}</td></tr>`;
    }).join("");
    $("#accTable").innerHTML = `<table><thead><tr><th>Sensors</th><th>Raw: model</th><th class="num">Acc %</th><th class="num">F1 %</th>
      <th>Baseline: model</th><th class="num">Acc %</th><th class="num">F1 %</th><th class="num">Paper acc %</th></tr></thead><tbody>${rows}</tbody></table>`;
  }
  document.querySelectorAll("[data-task]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-task]").forEach((x) => x.setAttribute("aria-pressed", x === b));
    accChart(b.dataset.task);
  }));
  $("#accTableBtn").addEventListener("click", (e) => {
    const t = $("#accTable");
    t.classList.toggle("hidden");
    e.target.textContent = t.classList.contains("hidden") ? "Show as table" : "Hide table";
  });
  accChart("binary");

  /* ------------------------------------------------------------ confusion matrices */
  (function confusion() {
    const mats = [
      ["Stress vs. no stress", ["No stress", "Stress"], [[3800, 123], [181, 1645]]],
      ["Three classes", ["Baseline", "Stress", "Amusement"], [[2467, 22, 490], [129, 1607, 90], [647, 72, 225]]],
    ];
    const ramp = ["--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6"];
    const host = $("#confusion");
    host.innerHTML = mats.map(([title, labels, m]) => {
      const rows = m.map((row, i) => {
        const tot = row.reduce((a, b) => a + b, 0);
        return `<tr><td>${labels[i]}</td>` + row.map((v) => {
          const p = v / tot, step = Math.min(5, Math.floor(p * 6));
          const ink = step >= 3 ? "var(--seq-ink-high)" : "var(--seq-ink-low)";
          return `<td class="num" style="background:var(${ramp[step]});color:${ink};font-weight:600" title="${v} windows">${Math.round(p * 100)}%</td>`;
        }).join("") + "</tr>";
      }).join("");
      return `<h4 style="margin:14px 0 6px">${title}</h4><div class="table-wrap"><table>
        <thead><tr><th>true ↓ / predicted →</th>${labels.map((l) => `<th class="num">${l}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
    }).join("");
  })();

  /* ------------------------------------------------------------ per subject */
  (function subjects() {
    const S = { 2: 78, 3: 89, 4: 100, 5: 100, 6: 100, 7: 99, 8: 99, 9: 100, 10: 100, 11: 89, 13: 97, 14: 99, 15: 87, 16: 84, 17: 98 };
    const data = Object.entries(S).sort((a, b) => b[1] - a[1]);
    const W = 520, H = 280, pad = { l: 40, r: 8, t: 14, b: 34 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Accuracy per subject" }, $("#subjChart"));
    const Y = (v) => pad.t + (1 - v / 100) * (H - pad.t - pad.b);
    [0, 50, 100].forEach((v) => {
      el("line", { x1: pad.l, x2: W - pad.r, y1: Y(v), y2: Y(v), class: v ? "gridline" : "baseline" }, svg);
      el("text", { x: pad.l - 6, y: Y(v) + 4, "text-anchor": "end" }, svg, v + "%");
    });
    const bw = (W - pad.l - pad.r) / data.length;
    const g = el("g", {}, svg);
    data.forEach(([s, v], i) => {
      const x = pad.l + i * bw + 1, w = bw - 2, y = Y(v), r = Math.min(4, w / 2);
      const bar = el("path", { class: "bar", fill: "var(--series-1)",
        d: `M${x} ${Y(0)} V${y + r} Q${x} ${y} ${x + r} ${y} H${x + w - r} Q${x + w} ${y} ${x + w} ${y + r} V${Y(0)} Z` }, g);
      el("text", { x: x + w / 2, y: H - pad.b + 16, "text-anchor": "middle", style: "font-size:10px" }, svg, "S" + s);
      const hit = el("rect", { x, y: pad.t, width: w, height: Y(0) - pad.t, fill: "transparent" }, g);
      hit.addEventListener("mousemove", (ev) => { g.classList.add("dim"); bar.classList.add("on");
        showTip(`<div class="k">WESAD subject S${s} (held out)</div><div>accuracy <b>${v} %</b></div>`, ev); });
      hit.addEventListener("mouseleave", () => { g.classList.remove("dim"); bar.classList.remove("on"); hideTip(); });
    });
    const mean = Object.values(S).reduce((a, b) => a + b, 0) / data.length;
    el("line", { x1: pad.l, x2: W - pad.r, y1: Y(mean), y2: Y(mean), stroke: "var(--text-primary)", "stroke-width": 1.5, "stroke-dasharray": "5 4" }, svg);
    el("text", { x: W - pad.r, y: Y(mean) - 6, "text-anchor": "end", style: "fill:var(--text-secondary)" }, svg, `mean ${mean.toFixed(1)}%`);
  })();
})();
