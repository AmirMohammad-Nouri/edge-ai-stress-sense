/* StressSense dashboard: WebSocket client that drives the diagram, charts and panels. */
(function () {
  const $ = (id) => document.getElementById(id);
  const { LineChart, BarChart } = window.Charts;
  Diagram.build();

  // ------------------------------------------------------------- theme
  const root = document.documentElement;
  root.dataset.theme = new URLSearchParams(location.search).get("theme") || localStorage.getItem("theme") || "dark";
  $("theme").onclick = () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", root.dataset.theme);
    [ppgC, gsrC, accC, micC].forEach((c) => (c.dirty = true));
    histC.draw();
  };

  // ------------------------------------------------------------- charts
  const ppgC = new LineChart($("cPPG"), { series: [{ name: "PPG", color: "--series-1" }], windowS: 8, fs: 64,
    decimals: 0, unit: "counts", tickDecimals: 0, minSpan: 50, empty: "start a measurement or signal check to stream the PPG" });
  const gsrC = new LineChart($("cGSR"), { series: [{ name: "GSR", color: "--series-2" }], windowS: 30, fs: 64,
    decimals: 3, unit: "µS", tickDecimals: 2, minSpan: 0.05, empty: "skin conductance streams during a measurement" });
  const accC = new LineChart($("cACC"), { series: [
      { name: "x", color: "--series-1" }, { name: "y", color: "--series-2" }, { name: "z", color: "--series-3" }],
    windowS: 10, fs: 32, decimals: 3, unit: "g", tickDecimals: 1, minSpan: 0.2, empty: "motion streams during a measurement (idle: 1 Hz)" });
  const micC = new LineChart($("cMIC"), { series: [{ name: "level", color: "--series-4" }], windowS: 30, fs: 10,
    decimals: 4, unit: "RMS", tickDecimals: 3, minSpan: 0.01, yMin: 0, empty: "waiting for the ESP32 microphone" });
  const histC = new BarChart($("cHIST"), { yMax: 1, empty: "no measurements yet" });

  // ------------------------------------------------------------- state
  let snap = null;
  let gsrCal = 512;
  let lastLink = null;      // link stats of the last measurement (shown when idle)
  const last = { vitals: 0, motion: 0, speech: 0 };
  const LEVEL = {
    low: { cls: "good", ic: "●", color: "--good" },
    moderate: { cls: "warn", ic: "▲", color: "--warning" },
    high: { cls: "bad", ic: "◆", color: "--critical" },
  };

  // Same conversion as tools/stress/measurement.py
  const gsrToUS = (raw) => {
    const x = (raw * (4.096 / 32768)) / 3.3 * 1023;
    const d = gsrCal - x;
    if (d <= 0.5) return NaN;
    return 1e6 / (((1024 + 2 * x) * 10000) / d);
  };

  // ------------------------------------------------------------- websocket
  let ws;
  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => { $("conn").textContent = "live"; $("conn").classList.add("ok"); };
    ws.onclose = () => { $("conn").textContent = "reconnecting…"; $("conn").classList.remove("ok"); setTimeout(connect, 1500); };
    ws.onmessage = (e) => handle(JSON.parse(e.data));
  }
  connect();

  function handle(m) {
    switch (m.type) {
      case "snapshot": onSnapshot(m); break;
      case "backlog": m.items.forEach((it) => handle({ ...it, _backlog: true })); break;
      case "vitals": onVitals(m); break;
      case "motion": onMotion(m); break;
      case "audio": onAudio(m); break;
      case "measure": onMeasure(m); break;
      case "result": onResult(m); break;
      case "transcript": addMsg("you", m.text || "(nothing recognised)", m.typed ? "typed" : `STT ${m.stt_ms ?? "?"} ms`);
        if (!m._backlog) { Diagram.flash("w_stt"); Diagram.flashNode("stt"); Diagram.flash("w_intent"); Diagram.flashNode("intent"); }
        break;
      case "reply": addMsg("bot", m.text, "assistant");
        if (!m._backlog) { Diagram.flash("w_tts", 3000); Diagram.flashNode("tts", 3000); }
        break;
      case "voice": onVoice(m); break;
      case "link": onLink(m); break;
      case "log": addLog(m.msg, m.t); break;
    }
  }

  // ------------------------------------------------------------- streams
  function onVitals(m) {
    last.vitals = Date.now();
    ppgC.push([m.ppg], 64);
    gsrC.push([m.gsr.map(gsrToUS)], 64);
    ["w_ppg", "w_gsr", "w_ads", "w_vitals"].forEach((w) => Diagram.flash(w, 800));
  }
  function onMotion(m) {
    last.motion = Date.now();
    accC.push([m.acc.map((a) => a[0]), m.acc.map((a) => a[1]), m.acc.map((a) => a[2])], 32);
    ["w_mpu", "w_motion"].forEach((w) => Diagram.flash(w, 800));
  }
  function onAudio(m) {
    micC.pushPoint([m.level || 0]);
    if (m.speech) { last.speech = Date.now(); Diagram.flash("w_mic", 900); Diagram.flash("w_audio", 900); Diagram.flashNode("mic", 900); }
  }


  // ------------------------------------------------------------- snapshot
  function onSnapshot(s) {
    snap = s;
    gsrCal = s.measurement.gsr_cal || 512;
    const e32 = s.devices.esp32, e86 = s.devices.esp8266;
    const comp = s.components;
    const meas = s.measurement;
    const busy = meas.state !== "idle";
    const collecting = meas.state === "collecting";
    const i32 = e32 || {}, i86 = e86 || {};

    // chips (status colour + icon + label)
    const chip = (label, st, txt) => {
      const map = { good: "●", warn: "▲", bad: "✕", off: "○" };
      return `<span class="chip ${st}"><span class="ic">${map[st]}</span>${label}${txt ? ` · ${txt}` : ""}</span>`;
    };
    const cs = (v) => (v === "ok" ? "good" : v === "off" ? "off" : v === "missing" ? "warn" : "bad");
    $("chips").innerHTML = [
      chip("ESP32", e32.online ? "good" : "bad", e32.online ? `${e32.rssi ?? "?"} dBm` : "offline"),
      chip("ESP8266", e86.online ? "good" : "bad", e86.online ? `${e86.rssi ?? "?"} dBm` : "offline"),
      chip("STT", cs(comp.stt), comp.stt), chip("TTS", cs(comp.tts), comp.tts),
      chip("LLM", cs(comp.llm), comp.llm),
      chip("Model", cs(comp.model), comp.model === "missing" ? "not trained" : comp.model),
      chip("Baseline", meas.baseline ? "good" : "warn", meas.baseline ? "calibrated" : "not set"),
    ].join("");

    // diagram nodes
    const peerOn = i32.peer && i32.peer.online;
    Diagram.setNode("esp32", { on: e32.online, active: busy,
      lines: e32.online ? [`IP ${e32.ip || "?"}`, `RSSI ${e32.rssi ?? "?"} dBm · heap ${Math.round((i32.heap || 0) / 1024)} kB`,
                           `up ${fmtUp(i32.uptime)} · ${i32.utterances ?? 0} utterances`] : ["", "", ""] });
    Diagram.setNode("mic", { on: e32.online && i32.mic_ok, active: Date.now() - last.speech < 1000 });
    Diagram.setNode("mpu", { on: e32.online && i32.mpu_ok, active: Date.now() - last.motion < 1500,
      warn: e32.online && !i32.mpu_ok, state: e32.online && !i32.mpu_ok ? "not found" : null });
    Diagram.setNode("esp8266", { on: e86.online, active: !!i86.collecting,
      lines: e86.online ? [`IP ${e86.ip || "?"}${i86.via ? " (via ESP32)" : ""}`, `RSSI ${e86.rssi ?? "?"} dBm`,
                           `up ${fmtUp(i86.uptime_s)} · ${i86.samples ?? 0} samples`] : ["", "", ""] });
    const adsOk = e86.online && i86.ads_ok;
    Diagram.setNode("ads", { on: adsOk, active: !!i86.collecting, warn: e86.online && !i86.ads_ok,
      state: e86.online && !i86.ads_ok ? "not found" : null });
    const worn = adsOk && isFinite(gsrToUS(i86.gsr_raw || 0));
    Diagram.setNode("ppg", { on: adsOk, active: !!i86.collecting });
    Diagram.setNode("gsr", { on: adsOk, active: !!i86.collecting, warn: adsOk && !worn,
      state: adsOk && !worn && !i86.collecting ? "not worn" : null });
    Diagram.setNode("led", { on: e86.online, lit: !!i86.collecting, state: i86.collecting ? "ON" : e86.online ? "off" : "offline" });
    Diagram.setNode("laptop", { on: true, active: busy,
      lines: [`state: ${meas.state}`, `ESP32 socket ${s.esp32_ws ? "open" : "closed"}`,
              meas.current ? `${meas.current.kind} · ${meas.current.path || "starting"}` : "ready"] });
    Diagram.setNode("stt", { on: comp.stt === "ok" });
    Diagram.setNode("intent", { on: true });
    Diagram.setNode("tts", { on: comp.tts === "ok", active: s.speaking });
    Diagram.setNode("features", { on: true, active: meas.state === "analyzing" });
    Diagram.setNode("model", { on: comp.model === "ok", warn: comp.model !== "ok", active: meas.state === "analyzing",
      state: comp.model === "ok" ? null : "not trained" });
    Diagram.setNode("dash", { on: true });

    // wires
    Diagram.setWire("w_mic", e32.online && i32.mic_ok);
    Diagram.setWire("w_mpu", e32.online && i32.mpu_ok);
    Diagram.setWire("w_ppg", adsOk); Diagram.setWire("w_gsr", adsOk); Diagram.setWire("w_ads", adsOk);
    Diagram.setWire("w_led", e86.online, !!i86.collecting);
    Diagram.setWire("w_peer", e32.online && (peerOn || e86.online), collecting && meas.current && meas.current.path === "esp32-relay");
    Diagram.setWire("w_audio", s.esp32_ws);
    Diagram.setWire("w_cmd", s.esp32_ws, false, true);
    Diagram.setWire("w_motion", e32.online);
    Diagram.setWire("w_vitals", e86.online);
    Diagram.setWire("w_stt", comp.stt === "ok"); Diagram.setWire("w_intent", comp.stt === "ok");
    Diagram.setWire("w_tts", comp.tts === "ok", s.speaking);
    Diagram.setWire("w_feat", true, meas.state === "analyzing"); Diagram.setWire("w_model", comp.model === "ok", meas.state === "analyzing");
    Diagram.setWire("w_dash", true);

    // idle trickle for the charts (1 Hz) so sensors visibly respond when not measuring
    if (!collecting && e32.online && i32.acc && Date.now() - last.motion > 2000) accC.pushPoint(i32.acc);

    // links table
    const lk = (meas.current && meas.current.vitals) ? meas.current : lastLink;
    const vit = lk && lk.vitals, mot = lk && lk.motion;
    const row = (name, rssi, rate, loss) =>
      `<tr><td>${name}</td><td>${rssi != null ? rssiBars(rssi) + rssi + " dBm" : "—"}</td><td>${rate ?? "—"}</td><td>${loss != null ? loss + " %" : "—"}</td></tr>`;
    $("links").querySelector("tbody").innerHTML = [
      row("ESP32 → laptop (WS)", e32.online ? e32.rssi : null, s.esp32_ws ? "1 Hz status" : null, null),
      row("ESP32 → laptop (motion)", e32.online ? e32.rssi : null, mot ? `${mot.rate_hz} Hz` : null, mot ? mot.loss_pct : null),
      row("ESP8266 → laptop (vitals)", e86.online ? e86.rssi : null, vit ? `${vit.rate_hz} Hz` : null, vit ? vit.loss_pct : null),
      row("ESP8266 ⇄ ESP32 (peer)", peerOn ? i32.peer.rssi : null, peerOn ? "1 Hz heartbeat" : null, null),
    ].join("");
    $("devinfo").innerHTML = [
      ["ESP8266 PPG raw", i86.ppg_raw ?? "—"], ["ESP8266 GSR raw", i86.gsr_raw ?? "—"],
      ["GSR now", isFinite(gsrToUS(i86.gsr_raw)) ? gsrToUS(i86.gsr_raw).toFixed(2) + " µS" : "not worn"],
      ["GSR zero (X_cal)", gsrCal],
    ].map(([k, v]) => `<div>${k}<br><b>${v}</b></div>`).join("");

    // history + calibration
    histC.set((meas.history || []).filter((h) => h.p_stress != null).map((h) => ({
      value: h.p_stress, color: (LEVEL[h.level] || {}).color,
      tip: `<div class="tk">${new Date(h.time * 1000).toLocaleString()}</div>` +
           `<div>P(stress): <b>${(100 * h.p_stress).toFixed(0)} %</b> · ${h.level}</div>` +
           `<div>HR ${h.hr ? h.hr.toFixed(0) : "—"} bpm · EDA ${h.eda ? h.eda.toFixed(2) : "—"} µS</div>`,
    })));
    $("calibInfo").innerHTML = meas.baseline
      ? `Personal baseline: <b>${meas.baseline.created}</b> (${meas.baseline.n_windows} windows) → personalised model`
      : `No personal baseline yet → population model. <b>Calibrate once while relaxed.</b>`;
    if (meas.model) {
      const b = meas.model.models[meas.baseline ? "binary_rel" : "binary_abs"];
      const fsName = { physio: "pulse + skin", all: "pulse + skin + motion", bvp: "pulse", eda: "skin", acc: "motion" }[meas.model.feature_set] || meas.model.feature_set;
      $("normBadge").textContent = `${b.clf} · ${fsName} · LOSO acc ${(100 * b.loso_accuracy).toFixed(0)} %`;
    } else $("normBadge").textContent = "model not trained";

    // buttons
    $("bMeasure").disabled = busy; $("bCalib").disabled = busy; $("bPreview").disabled = busy;
    $("bStop").disabled = !busy;
    if (!busy) $("progress").classList.add("hidden");
  }

  const fmtUp = (s) => (s == null ? "?" : s > 3600 ? `${(s / 3600).toFixed(1)} h` : s > 60 ? `${Math.floor(s / 60)} min` : `${s} s`);
  function rssiBars(r) {
    const n = r > -55 ? 4 : r > -65 ? 3 : r > -75 ? 2 : 1;
    return `<span class="rssi">${[4, 7, 10, 12].map((h, i) => `<i class="${i < n ? "f" : ""}" style="height:${h}px"></i>`).join("")}</span>`;
  }

  // ------------------------------------------------------------- measurement
  function onMeasure(m) {
    $("progress").classList.remove("hidden");
    const names = { measure: "Measuring stress", calibrate: "Calibrating baseline", preview: "Signal check" };
    const phase = m.phase === "analyzing" ? "Analysing…" : m.phase === "starting" ? "Contacting devices…" : names[m.kind];
    $("progLabel").textContent = phase + (m.path ? `  ·  ${m.path === "esp32-relay" ? "via ESP32 relay" : "direct to ESP8266"}` : "");
    $("progTime").textContent = `${Math.round(m.elapsed_s || 0)} / ${m.duration_s} s`;
    $("progBar").style.width = `${Math.min(100, (100 * (m.elapsed_s || 0)) / m.duration_s)}%`;
    if (m.vitals) $("progVitals").textContent = `PPG/GSR ${m.vitals.samples} samples · ${m.vitals.loss_pct}% lost`;
    if (m.live_hr) ppgC.setReadout(`HR (last 10 s) <b>${m.live_hr.toFixed(0)}</b> bpm`);
    if (m.vitals) lastLink = { vitals: m.vitals, motion: m.motion };
    if (m.motion) $("progMotion").textContent = `motion ${m.motion.samples} samples · ${m.motion.loss_pct}% lost`;
    if (m.phase === "starting" && !m._backlog) { ppgC.clear(); gsrC.clear(); accC.clear(); ppgC.setReadout(""); }
  }

  function onResult(r) {
    if (r._backlog && r.kind !== "measure") return;
    $("progress").classList.add("hidden");
    $("warnings").innerHTML = (r.warnings || []).map((w) => `<div class="warn-item">${w}</div>`).join("") +
      (r.ok ? "" : `<div class="warn-item">${r.reason}</div>`);
    if (r.link) lastLink = r.link;
    if (!r.ok) return;
    const f = r.features || {};
    $("sHR").textContent = f.hr_mean != null ? f.hr_mean.toFixed(0) : "—";
    $("sRMSSD").textContent = f.rmssd != null ? f.rmssd.toFixed(0) : "—";
    $("sEDA").textContent = f.eda_mean != null ? f.eda_mean.toFixed(2) : "—";
    $("sSCR").textContent = f.scr_n_peaks != null ? f.scr_n_peaks.toFixed(0) : "—";
    renderFeatures(f);
    if (!r._backlog) { Diagram.flash("w_dash", 2500); Diagram.flashNode("dash", 2500); }
    if (r.kind !== "measure") return;
    const p = r.prediction;
    if (!p) {
      setGauge(null, null, "model not trained yet");
      $("probs").innerHTML = "";
      return;
    }
    setGauge(p.p_stress, r.level);
    const labels = { baseline: "Neutral", stress: "Stress", amusement: "Amusement" };
    $("probs").innerHTML = `<div class="meta" style="margin-bottom:2px">Affective state (3-class, ${p.norm === "rel" ? "personalised" : "population"} model)</div>` +
      Object.entries(p["3class"]).map(([k, v]) =>
        `<div class="prob"><span>${labels[k] || k}</span><div class="pb"><div style="width:${100 * v}%"></div></div><span class="pv">${(100 * v).toFixed(0)}%</span></div>`).join("");
  }

  function setGauge(p, level, text) {
    const fill = $("gFill");
    if (p == null) {
      fill.style.strokeDasharray = "0 400";
      fill.style.strokeOpacity = 0;
      $("gValue").textContent = "—";
      $("gLevel").textContent = text || "";
      return;
    }
    const L = LEVEL[level] || LEVEL.low;
    fill.style.strokeOpacity = 1;
    fill.style.strokeDasharray = `${Math.max(1, p * 314.16)} 400`;
    fill.style.stroke = `var(${L.color})`;
    $("gValue").textContent = `${Math.round(p * 100)}%`;
    $("gLevel").innerHTML = `<span class="ic" style="color:var(${L.color})">${L.ic}</span>${level} stress · P(stress)`;
  }

  const FEAT_GROUPS = {
    "Heart (PPG → beats)": { hr_mean: ["HR mean", "bpm", 1], hr_std: ["HR std", "bpm", 1], hr_min: ["HR min", "bpm", 0], hr_max: ["HR max", "bpm", 0],
      nn_mean: ["NN mean", "ms", 0], nn_std: ["SDNN", "ms", 1], rmssd: ["RMSSD", "ms", 1], nn50: ["NN50", "", 0], pnn50: ["pNN50", "", 2],
      nn_iqr: ["NN IQR", "ms", 1], hrv_lf: ["LF power (log)", "", 2], hrv_hf: ["HF power (log)", "", 2], hrv_uhf: ["UHF power (log)", "", 2],
      hrv_lf_hf: ["log LF/HF", "", 2], hrv_total: ["Total power (log)", "", 2], hrv_lf_norm: ["LF norm", "", 2], hrv_hf_norm: ["HF norm", "", 2],
      hrv_rel_lf: ["LF relative", "", 2], hrv_rel_hf: ["HF relative", "", 2] },
    "Skin (GSR → EDA)": { eda_mean: ["EDA mean", "µS", 3], eda_std: ["EDA std", "µS", 3], eda_min: ["EDA min", "µS", 3], eda_max: ["EDA max", "µS", 3],
      eda_range: ["EDA range", "µS", 3], eda_slope: ["EDA slope", "µS/s", 4], scl_mean: ["SCL mean", "µS", 3], scl_std: ["SCL std", "µS", 3],
      scr_std: ["SCR std", "µS", 3], scl_corr_t: ["corr(SCL, t)", "", 2], scr_n_peaks: ["SCR peaks", "", 0], scr_amp_sum: ["Σ SCR amplitude", "µS", 3],
      scr_area: ["SCR area", "µS·s", 2] },
    "Motion (MPU6050)": { acc_3d_mean: ["|a| mean", "g", 3], acc_3d_std: ["|a| std", "g", 3], acc_x_std: ["x std", "g", 3], acc_y_std: ["y std", "g", 3],
      acc_z_std: ["z std", "g", 3], acc_3d_absint: ["|a| abs. integral", "g", 3], acc_x_absint: ["x abs. integral", "g", 3],
      acc_y_absint: ["y abs. integral", "g", 3], acc_z_absint: ["z abs. integral", "g", 3], acc_x_peakf: ["x peak freq", "Hz", 2],
      acc_y_peakf: ["y peak freq", "Hz", 2], acc_z_peakf: ["z peak freq", "Hz", 2] },
  };
  function renderFeatures(f) {
    $("featTable").innerHTML = Object.entries(FEAT_GROUPS).map(([g, items]) =>
      `<div class="feat-group"><h3>${g}</h3>` + Object.entries(items).map(([k, [label, unit, d]]) =>
        `<div class="feat-row"><span>${label}</span><span>${f[k] == null ? "—" : f[k].toFixed(d)} ${unit}</span></div>`).join("") + "</div>").join("");
  }

  // ------------------------------------------------------------- voice / log
  function onVoice(m) {
    if (m.event === "speech_start" && !m._backlog) { Diagram.flash("w_audio", 2000); Diagram.flashNode("mic", 2000); }
    if (m.event === "intent" && m.intent) addMsg("sys", `command recognised: ${m.intent}`);
  }
  function onLink(m) {
    if (m._backlog) { addLog(`${m.path}: ${m.event}`, m.t); return; }
    if (m.path === "laptop->esp32") Diagram.pulse("w_cmd");
    if (m.path === "esp32->esp8266" && m.event === "ack") { Diagram.pulse("w_peer"); Diagram.pulse("w_peer", true); }
    if (m.path === "laptop->esp8266") Diagram.pulse("w_vitals", true);
    const extra = m.tries ? ` (after ${m.tries} tries)` : m.peer_samples ? ` (${m.peer_samples} samples)` :
                  m.motion_samples ? ` (${m.motion_samples} samples)` : "";
    addLog(`${m.path}: ${m.event}${extra}`, m.t);
  }
  function addMsg(who, text, meta) {
    const d = document.createElement("div");
    d.className = `msg ${who}`;
    d.textContent = text;
    if (meta) { const s = document.createElement("span"); s.className = "mt"; s.textContent = meta; d.appendChild(s); }
    const f = $("voiceFeed");
    f.appendChild(d);
    while (f.children.length > 60) f.firstChild.remove();
    f.scrollTop = f.scrollHeight;
  }
  function addLog(text, t) {
    const d = document.createElement("div");
    d.className = "logline";
    d.innerHTML = `<time>${new Date((t || Date.now() / 1000) * 1000).toLocaleTimeString()}</time>`;
    d.appendChild(document.createTextNode(text));
    const f = $("eventLog");
    f.appendChild(d);
    while (f.children.length > 200) f.firstChild.remove();
    f.scrollTop = f.scrollHeight;
  }

  // ------------------------------------------------------------- actions
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) }).then((r) => r.json());
  $("bMeasure").onclick = () => post("/api/measure", { kind: "measure" });
  $("bCalib").onclick = () => post("/api/measure", { kind: "calibrate" });
  $("bPreview").onclick = () => post("/api/measure", { kind: "preview" });
  $("bStop").onclick = () => post("/api/stop");
  $("bGsrCal").onclick = () => {
    if (confirm("Take the GSR electrodes off your fingers, then press OK to store the 'not worn' reading.")) {
      post("/api/gsr_calibrate").then((r) => addLog(r.ok ? `GSR zero set: X_cal = ${r.x_cal}` : `GSR zero failed: ${r.reason}`));
    }
  };
  $("sayForm").onsubmit = (e) => {
    e.preventDefault();
    const t = $("sayInput").value.trim();
    if (t) post("/api/say", { text: t });
    $("sayInput").value = "";
  };
})();
