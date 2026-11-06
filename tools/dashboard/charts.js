/* Tiny dependency-free canvas charts: streaming line chart + bar chart.
   2px lines, recessive grid, crosshair + tooltip on hover. */
(function () {
  const css = (name) => getComputedStyle(document.querySelector(".viz-root")).getPropertyValue(name).trim();
  const tooltip = () => document.getElementById("tooltip");

  function setupCanvas(el) {
    const c = document.createElement("canvas");
    el.appendChild(c);
    const ctx = c.getContext("2d");
    const resize = () => {
      const r = el.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      c.width = Math.max(1, r.width * dpr);
      c.height = Math.max(1, r.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    new ResizeObserver(resize).observe(el);
    return { c, ctx, size: () => el.getBoundingClientRect() };
  }

  function niceTicks(lo, hi, n = 4) {
    const span = hi - lo || 1;
    const step0 = span / n;
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  const fmt = (v, d = 2) => (v == null || !isFinite(v) ? "—" : Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(d));

  /* ---------------------------------------------------------------- line */
  class LineChart {
    constructor(el, opts) {
      this.el = el;
      this.o = Object.assign({ windowS: 10, fs: 64, decimals: 2, unit: "", minSpan: 0, yMin: null, yMax: null }, opts);
      this.series = this.o.series.map((s) => ({ ...s, data: [] }));   // data: [t, v]
      this.t = 0;
      this.hover = null;
      this.cv = setupCanvas(el);
      if (this.series.length > 1) {
        const lg = document.createElement("div");
        lg.className = "legend";
        lg.innerHTML = this.series.map((s) => `<span><i style="background:${css(s.color)}"></i>${s.name}</span>`).join("");
        this.legend = lg;
        el.appendChild(lg);
      }
      this.readout = document.createElement("div");
      this.readout.className = "readout";
      el.appendChild(this.readout);
      this.emptyEl = document.createElement("div");
      this.emptyEl.className = "empty";
      this.emptyEl.textContent = this.o.empty || "waiting for data";
      el.appendChild(this.emptyEl);
      el.addEventListener("mousemove", (e) => this.onMove(e));
      el.addEventListener("mouseleave", () => { this.hover = null; tooltip().classList.add("hidden"); });
      this.dirty = true;
      const loop = () => { if (this.dirty) this.draw(); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }

    /* Append samples; `values` is an array per series (same length), sampled at fs. */
    push(values, fs = this.o.fs) {
      const n = values[0].length;
      for (let i = 0; i < n; i++) {
        this.t += 1 / fs;
        this.series.forEach((s, k) => s.data.push([this.t, values[k][i]]));
      }
      const cut = this.t - this.o.windowS;
      this.series.forEach((s) => { let j = 0; while (j < s.data.length && s.data[j][0] < cut) j++; if (j) s.data.splice(0, j); });
      this.dirty = true;
    }
    pushPoint(vals) {               // irregular point (e.g. 1 Hz status): advance by real time
      const now = performance.now() / 1000;
      const dt = this.lastPt ? Math.min(2, now - this.lastPt) : 0.1;
      this.lastPt = now;
      this.push(vals.map((v) => [v]), 1 / dt);
    }
    clear() { this.series.forEach((s) => (s.data = [])); this.t = 0; this.dirty = true; }
    setReadout(html) { this.readout.innerHTML = html; }
    setEmpty(text) { this.emptyEl.textContent = text; }

    onMove(e) {
      const r = this.cv.size();
      this.hover = e.clientX - r.left;
      this.dirty = true;
      this.mouse = e;
    }

    draw() {
      this.dirty = false;
      const { ctx } = this.cv;
      const { width: W, height: H } = this.cv.size();
      ctx.clearRect(0, 0, W, H);
      const pad = { l: 46, r: 10, t: 22, b: 20 };
      const has = this.series.some((s) => s.data.length > 1);
      this.emptyEl.style.display = has ? "none" : "flex";
      // y range
      let lo = Infinity, hi = -Infinity;
      this.series.forEach((s) => s.data.forEach(([, v]) => { if (isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      if (this.o.yMin != null) lo = Math.min(lo, this.o.yMin);
      if (this.o.yMax != null) hi = Math.max(hi, this.o.yMax);
      if (hi - lo < this.o.minSpan) { const m = (hi + lo) / 2; lo = m - this.o.minSpan / 2; hi = m + this.o.minSpan / 2; }
      const padY = (hi - lo) * 0.08 || 1;
      lo -= padY; hi += padY;
      const t1 = this.t, t0 = t1 - this.o.windowS;
      const X = (t) => pad.l + ((t - t0) / (t1 - t0)) * (W - pad.l - pad.r);
      const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
      // grid + y ticks
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillStyle = css("--text-muted");
      ctx.strokeStyle = css("--grid");
      ctx.lineWidth = 1;
      niceTicks(lo, hi, 4).forEach((v) => {
        const y = Math.round(Y(v)) + 0.5;
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
        ctx.textAlign = "right"; ctx.textBaseline = "middle";
        ctx.fillText(fmt(v, this.o.tickDecimals ?? 1), pad.l - 6, y);
      });
      // x axis label (seconds ago)
      ctx.strokeStyle = css("--axis");
      ctx.beginPath(); ctx.moveTo(pad.l, H - pad.b + 0.5); ctx.lineTo(W - pad.r, H - pad.b + 0.5); ctx.stroke();
      ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.fillStyle = css("--text-muted");
      for (let s = 0; s <= this.o.windowS; s += this.o.windowS / 5) {
        ctx.fillText(s === 0 ? "now" : `-${s.toFixed(0)}s`, X(t1 - s), H - pad.b + 4);
      }
      // series
      this.series.forEach((s) => {
        if (s.data.length < 2) return;
        ctx.strokeStyle = css(s.color);
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.beginPath();
        let started = false;
        const step = Math.max(1, Math.floor(s.data.length / (W * 1.5)));
        for (let i = 0; i < s.data.length; i += step) {
          const [t, v] = s.data[i];
          if (!isFinite(v)) { started = false; continue; }
          if (!started) { ctx.moveTo(X(t), Y(v)); started = true; } else ctx.lineTo(X(t), Y(v));
        }
        ctx.stroke();
        if (s.markers) {
          ctx.fillStyle = css(s.color);
          s.markers.forEach((t) => { if (t >= t0) { ctx.beginPath(); ctx.arc(X(t), pad.t + 4, 3, 0, 7); ctx.fill(); } });
        }
      });
      // crosshair
      if (this.hover != null && has && this.hover > pad.l) {
        const t = t0 + ((this.hover - pad.l) / (W - pad.l - pad.r)) * (t1 - t0);
        ctx.strokeStyle = css("--text-muted");
        ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(this.hover + 0.5, pad.t); ctx.lineTo(this.hover + 0.5, H - pad.b); ctx.stroke();
        ctx.setLineDash([]);
        const rows = this.series.map((s) => {
          let best = null;
          for (const p of s.data) { if (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p; }
          if (best) {
            ctx.fillStyle = css(s.color);
            ctx.strokeStyle = css("--surface-1"); ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(X(best[0]), Y(best[1]), 4, 0, 7); ctx.fill(); ctx.stroke();
          }
          return `<div><i style="background:${css(s.color)}"></i>${s.name}: <b>${best ? fmt(best[1], this.o.decimals) : "—"}</b> ${this.o.unit}</div>`;
        });
        const tt = tooltip();
        tt.innerHTML = `<div class="tk">${(t1 - t).toFixed(1)} s ago</div>` + rows.join("");
        tt.style.left = this.mouse.clientX + 14 + "px";
        tt.style.top = this.mouse.clientY + 10 + "px";
        tt.classList.remove("hidden");
      }
    }
  }

  /* ----------------------------------------------------------------- bars */
  class BarChart {
    constructor(el, opts) {
      this.el = el;
      this.o = Object.assign({ yMax: 1, color: "--series-1" }, opts);
      this.items = [];
      this.cv = setupCanvas(el);
      this.emptyEl = document.createElement("div");
      this.emptyEl.className = "empty";
      this.emptyEl.textContent = this.o.empty || "no data";
      el.appendChild(this.emptyEl);
      el.addEventListener("mousemove", (e) => { this.mouse = e; this.draw(); });
      el.addEventListener("mouseleave", () => { this.mouse = null; tooltip().classList.add("hidden"); this.draw(); });
      new ResizeObserver(() => this.draw()).observe(el);
    }
    set(items) { this.items = items; this.draw(); }
    draw() {
      const { ctx } = this.cv;
      const { width: W, height: H, left } = this.cv.size();
      ctx.clearRect(0, 0, W, H);
      this.emptyEl.style.display = this.items.length ? "none" : "flex";
      const pad = { l: 34, r: 6, t: 8, b: 18 };
      const n = Math.max(this.items.length, 8);
      const bw = (W - pad.l - pad.r) / n;
      const Y = (v) => pad.t + (1 - v / this.o.yMax) * (H - pad.t - pad.b);
      ctx.font = "11px system-ui, sans-serif";
      [0, 0.5, 1].forEach((v) => {
        const y = Math.round(Y(v)) + 0.5;
        ctx.strokeStyle = v === 0 ? css("--axis") : css("--grid");
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
        ctx.fillStyle = css("--text-muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
        ctx.fillText(`${v * 100}%`, pad.l - 5, y);
      });
      let hoverIdx = -1;
      if (this.mouse) hoverIdx = Math.floor((this.mouse.clientX - left - pad.l) / bw);
      this.items.forEach((it, i) => {
        const x = pad.l + i * bw + 1, w = Math.max(2, bw - 2);       // 2px surface gap
        const y = Y(it.value), h = Y(0) - y;
        ctx.fillStyle = css(it.color || this.o.color);
        ctx.globalAlpha = hoverIdx === -1 || hoverIdx === i ? 1 : 0.45;
        const r = Math.min(4, w / 2, h);
        ctx.beginPath();
        ctx.moveTo(x, Y(0)); ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r); ctx.lineTo(x + w, Y(0));
        ctx.fill();
        ctx.globalAlpha = 1;
      });
      if (this.items[hoverIdx]) {
        const tt = tooltip();
        tt.innerHTML = this.items[hoverIdx].tip;
        tt.style.left = this.mouse.clientX + 14 + "px";
        tt.style.top = this.mouse.clientY + 10 + "px";
        tt.classList.remove("hidden");
      } else if (this.mouse) tooltip().classList.add("hidden");
    }
  }

  window.Charts = { LineChart, BarChart, css };
})();
