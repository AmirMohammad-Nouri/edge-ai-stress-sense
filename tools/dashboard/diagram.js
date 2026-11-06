/* Live system diagram: nodes + wires whose state follows the snapshot/events. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  };

  // x, y, w, h, title, subtitle
  const NODES = {
    mic:     [20, 24, 150, 64, "INMP441 mic", "I2S · 16 kHz", "--series-4"],
    mpu:     [20, 108, 150, 64, "MPU6050", "I2C 0x68 · 32 Hz", "--series-3"],
    esp32:   [250, 36, 180, 124, "ESP32", "coordinator", "--series-1", true],
    ppg:     [20, 240, 150, 64, "PPG pulse sensor", "ADS A0 · 64 Hz", "--series-1"],
    gsr:     [20, 324, 150, 64, "Grove GSR", "ADS A1 · 64 Hz", "--series-2"],
    ads:     [196, 276, 108, 78, "ADS1115", "16-bit · 0x48", "--series-1"],
    esp8266: [330, 262, 180, 110, "ESP8266", "vitals node", "--series-2", true],
    led:     [196, 372, 120, 64, "LED", "D5 · collecting", "--series-4"],
    laptop:  [600, 140, 170, 160, "Laptop server", "WS :8765 · UDP 4211-13", "--series-1", true],
    stt:     [808, 22, 146, 64, "Speech-to-text", "Moonshine", "--series-4"],
    intent:  [970, 22, 115, 64, "Intent", "rule matcher", "--series-4"],
    tts:     [970, 108, 115, 64, "Voice reply", "Piper TTS", "--series-4"],
    features:[808, 200, 146, 64, "Features", "WESAD wrist set", "--series-3"],
    model:   [970, 200, 115, 64, "ML model", "stress classifier", "--series-3"],
    dash:    [890, 330, 160, 64, "Dashboard", "this page", "--series-1"],
  };

  // id: [from node, side, to node, side, label, color, opts]
  const WIRES = {
    w_mic:   ["mic", "r", "esp32", "l", "", "--series-4"],
    w_mpu:   ["mpu", "r", "esp32", "l", "", "--series-3"],
    w_ppg:   ["ppg", "r", "ads", "l", "", "--series-1"],
    w_gsr:   ["gsr", "r", "ads", "l", "", "--series-2"],
    w_ads:   ["ads", "r", "esp8266", "l", "", "--series-1"],
    w_led:   ["esp8266", "b", "led", "r", "", "--series-4"],
    w_peer:  ["esp32", "b", "esp8266", "t", "WiFi UDP · START / ACK / heartbeat", "--accent", { wifi: true }],
    w_audio: ["esp32", "r", "laptop", "l", "WebSocket · audio + status", "--series-4", { wifi: true, dy1: -30, dy2: -40, lx: 440, ly: 40, anchor: "start" }],
    w_cmd:   ["laptop", "l", "esp32", "r", "", "--accent", { wifi: true, dy1: -62, dy2: -48, hidden: true }],
    w_motion:["esp32", "r", "laptop", "l", "UDP · motion 32 Hz", "--series-3", { wifi: true, dy1: 30, dy2: 0, lx: 446, ly: 120, anchor: "start" }],
    w_vitals:["esp8266", "r", "laptop", "l", "UDP · PPG + GSR 64 Hz", "--series-2", { wifi: true, dy1: 0, dy2: 50, lx: 520, ly: 352, anchor: "start" }],
    w_stt:   ["laptop", "r", "stt", "l", "", "--series-4", { dy1: -50 }],
    w_intent:["stt", "r", "intent", "l", "", "--series-4"],
    w_tts:   ["intent", "b", "tts", "t", "", "--series-4"],
    w_feat:  ["laptop", "r", "features", "l", "", "--series-3", { dy1: 20 }],
    w_model: ["features", "r", "model", "l", "", "--series-3"],
    w_dash:  ["model", "b", "dash", "t", "", "--series-1"],
  };

  const anchor = (id, side, dy = 0) => {
    const [x, y, w, h] = NODES[id];
    return { l: [x, y + h / 2 + dy], r: [x + w, y + h / 2 + dy], t: [x + w / 2, y], b: [x + w / 2, y + h] }[side];
  };

  const nodeEls = {}, wireEls = {};
  const wireUntil = {};      // id -> timestamp until which it shows "flow"
  const nodeUntil = {};

  function build() {
    const svg = document.getElementById("diagram");
    const gW = svg.querySelector("#wires"), gN = svg.querySelector("#nodes");
    for (const [id, [a, sa, b, sb, label, color, o = {}]] of Object.entries(WIRES)) {
      const [x1, y1] = anchor(a, sa, o.dy1 || 0), [x2, y2] = anchor(b, sb, o.dy2 || 0);
      const horiz = sa === "l" || sa === "r";
      const dx = (x2 - x1) / 2, dy = (y2 - y1) / 2;
      const d = horiz
        ? `M${x1} ${y1} C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`
        : `M${x1} ${y1} C${x1} ${y1 + dy} ${x2} ${y2 - dy} ${x2} ${y2}`;
      const p = el("path", { d, class: "wire" + (o.wifi ? " wifi" : ""), id }, gW);
      p.style.setProperty("--wcolor", `var(${color})`);
      if (o.hidden) p.style.opacity = 0;
      wireEls[id] = { p, o };
      if (label) {
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        const lx = o.lx ?? (id === "w_peer" ? mx + 10 : mx), ly = o.ly ?? my - 6;
        const t = el("text", { x: lx, y: ly, class: "wire-label",
                               "text-anchor": o.anchor || (id === "w_peer" ? "start" : "middle") }, gW);
        t.textContent = label;
        wireEls[id].label = t;
      }
    }
    for (const [id, [x, y, w, h, title, sub, color, big]] of Object.entries(NODES)) {
      const g = el("g", { class: "node" + (big ? " big" : ""), id: "n_" + id }, gN);
      g.style.setProperty("--ncolor", `var(${color})`);
      el("rect", { class: "box", x, y, width: w, height: h, rx: 10 }, g);
      el("circle", { class: "dot", cx: x + w - 12, cy: y + 12, r: 4 }, g);
      const t = el("text", { class: "title", x: x + 12, y: y + 22 }, g); t.textContent = title;
      const s = el("text", { class: "sub", x: x + 12, y: y + 38 }, g); s.textContent = sub;
      const st = el("text", { class: "stateTxt", x: x + 12, y: y + h - 9 }, g); st.textContent = "offline";
      const extra = [];
      if (big) for (let i = 0; i < 3; i++) {
        const e = el("text", { class: "sub", x: x + 12, y: y + 56 + i * 15 }, g);
        extra.push(e);
      }
      if (id === "led") {
        el("circle", { class: "led-halo", cx: x + w - 24, cy: y + h / 2 + 6, r: 18, fill: "url(#ledGlow)" }, g);
        el("circle", { class: "led-bulb", cx: x + w - 24, cy: y + h / 2 + 6, r: 7 }, g);
      }
      nodeEls[id] = { g, st, sub: s, extra };
    }
  }

  function setNode(id, { on, active, warn, state, lines, lit }) {
    const n = nodeEls[id];
    if (!n) return;
    const act = active || (nodeUntil[id] || 0) > Date.now();
    n.g.classList.toggle("on", !!on);
    n.g.classList.toggle("active", !!(on && act));
    n.g.classList.toggle("warn", !!warn);
    n.g.classList.toggle("lit", !!lit);
    n.st.textContent = state || (on ? (act ? "active" : "online") : "offline");
    if (lines) lines.forEach((l, i) => { if (n.extra[i]) n.extra[i].textContent = l; });
  }

  function setWire(id, on, flow, reverse = false) {
    const w = wireEls[id];
    if (!w) return;
    const f = flow || (wireUntil[id] || 0) > Date.now();
    w.p.classList.toggle("on", !!on);
    w.p.classList.toggle("flow", !!(on && f));
    w.p.classList.toggle("rev", !!reverse);
    if (w.o.hidden) w.p.style.opacity = on && f ? 1 : 0;
    if (w.label) w.label.classList.toggle("flow", !!(on && f));
  }

  /* One-shot packet dot travelling along a wire (for commands / ACKs). */
  function pulse(id, reverse = false) {
    const w = wireEls[id];
    if (!w) return;
    const g = document.querySelector("#pulses");
    const c = el("circle", { r: 5, class: "pulse" }, g);
    c.style.fill = getComputedStyle(w.p).getPropertyValue("--wcolor") ? `var(--accent)` : "";
    const len = w.p.getTotalLength();
    const t0 = performance.now(), dur = 700;
    const step = (now) => {
      const k = Math.min(1, (now - t0) / dur);
      const pt = w.p.getPointAtLength((reverse ? 1 - k : k) * len);
      c.setAttribute("cx", pt.x); c.setAttribute("cy", pt.y);
      if (k < 1) requestAnimationFrame(step); else c.remove();
    };
    requestAnimationFrame(step);
  }

  const flash = (id, ms = 1500) => { wireUntil[id] = Date.now() + ms; };
  const flashNode = (id, ms = 1500) => { nodeUntil[id] = Date.now() + ms; };

  window.Diagram = { build, setNode, setWire, pulse, flash, flashNode };
})();
