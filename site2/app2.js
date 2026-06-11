/* ============================================================
   BUOYCAST · site2 · app2.js
   Live feed -> live strip + dark fan chart. Graceful fallback.
   ============================================================ */

const DATA_URL = "https://34.172.202.78.sslip.io/data.json";

const ACCENT = "#9cc8da";
const WHITE = "#f2f4f6";
const MUTED = "#8b95a1";
const LINE = "#1c1f24";

/* ---------- scroll reveal ---------- */
(function reveal() {
  const els = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) {
    els.forEach((e) => e.classList.add("in"));
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) {
          en.target.classList.add("in");
          io.unobserve(en.target);
        }
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
  );
  els.forEach((e) => io.observe(e));
})();

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const f1 = (x) => (x == null ? "—" : x.toFixed(1));

function fmtUpdated(iso) {
  try {
    const d = new Date(iso);
    const opt = {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone: "America/Chicago",
    };
    return "UPDATED " + d.toLocaleString("en-US", opt).toUpperCase() + " CT";
  } catch {
    return "UPDATED —";
  }
}

function trajAt(traj, h) {
  return traj.find((r) => r.h === h) || null;
}

/* ---------- live strip ---------- */
function fillStrip(d) {
  const n = d.now || {};
  $("s-water").textContent = f1(n.wtmp_f);
  $("s-air").textContent = f1(n.atmp_f);
  $("s-wave").textContent = f1(n.wvht_ft);
  $("s-wind").textContent = f1(n.wspd_kt);
  $("live-updated").textContent = fmtUpdated(d.generated_utc);

  const t24 = trajAt(d.trajectory, 24);
  const t168 = trajAt(d.trajectory, 168);
  if (t24) {
    $("s-24").textContent = f1(t24.p50);
    $("s-24band").textContent = `°F · ${f1(t24.p05)}–${f1(t24.p95)}`;
  }
  if (t168) {
    $("s-168").textContent = f1(t168.p50);
    $("s-168band").textContent = `°F · ${f1(t168.p05)}–${f1(t168.p95)}`;
  }
}

/* fallback: last-known plausible numbers, clearly flagged */
function fillStripFallback() {
  const fb = { wtmp_f: 64.0, atmp_f: 69.5, wvht_ft: 2.3, wspd_kt: 18.5 };
  $("s-water").textContent = f1(fb.wtmp_f);
  $("s-air").textContent = f1(fb.atmp_f);
  $("s-wave").textContent = f1(fb.wvht_ft);
  $("s-wind").textContent = f1(fb.wspd_kt);
  $("s-24").textContent = "63.2";
  $("s-24band").textContent = "°F · 61.2–65.4";
  $("s-168").textContent = "63.5";
  $("s-168band").textContent = "°F · 60.1–67.5";
  $("live-updated").textContent = "LIVE FEED UNREACHABLE";
  const note = $("live-note");
  if (note) note.hidden = false;
}

/* ---------- fan chart ---------- */
function drawFan(d) {
  const canvas = $("fanCanvas");
  if (!canvas) return;
  const traj = d.trajectory || [];
  const members = d.members || [];
  if (!traj.length) return;

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const cssW = canvas.clientWidth;
  const cssH = canvas.clientHeight;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const padL = 52, padR = 18, padT = 18, padB = 34;
  const W = cssW - padL - padR;
  const H = cssH - padT - padB;

  const N = traj.length; // 168
  // y domain from p05/p95 of bands plus member extremes
  let lo = Infinity, hi = -Infinity;
  traj.forEach((r) => { lo = Math.min(lo, r.p05); hi = Math.max(hi, r.p95); });
  members.forEach((m) => m.traj.forEach((v) => { lo = Math.min(lo, v); hi = Math.max(hi, v); }));
  const padY = (hi - lo) * 0.08 || 1;
  lo -= padY; hi += padY;

  const x = (i) => padL + (i / (N - 1)) * W;
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * H;

  /* --- grid + y labels --- */
  ctx.font = "11px 'Space Mono', monospace";
  ctx.textBaseline = "middle";
  const ticks = 5;
  for (let i = 0; i <= ticks; i++) {
    const v = lo + (i / ticks) * (hi - lo);
    const yy = y(v);
    ctx.strokeStyle = LINE;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, yy + 0.5);
    ctx.lineTo(padL + W, yy + 0.5);
    ctx.stroke();
    ctx.fillStyle = MUTED;
    ctx.textAlign = "right";
    ctx.fillText(v.toFixed(0) + "°", padL - 10, yy);
  }

  /* --- x labels (days) --- */
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let day = 0; day <= 7; day++) {
    const h = day * 24;
    const i = Math.min(h, N - 1);
    const xx = x(i);
    ctx.fillStyle = MUTED;
    ctx.fillText(day === 0 ? "NOW" : "+" + day + "D", xx, padT + H + 10);
    if (day > 0 && day < 7) {
      ctx.strokeStyle = "rgba(28,31,36,0.6)";
      ctx.beginPath();
      ctx.moveTo(xx + 0.5, padT);
      ctx.lineTo(xx + 0.5, padT + H);
      ctx.stroke();
    }
  }

  /* --- 90% band (p05..p95) --- */
  function bandPath(loKey, hiKey) {
    ctx.beginPath();
    traj.forEach((r, i) => {
      const xx = x(i), yy = y(r[hiKey]);
      i === 0 ? ctx.moveTo(xx, yy) : ctx.lineTo(xx, yy);
    });
    for (let i = N - 1; i >= 0; i--) {
      ctx.lineTo(x(i), y(traj[i][loKey]));
    }
    ctx.closePath();
  }
  ctx.fillStyle = "rgba(99,150,200,0.15)";
  bandPath("p05", "p95");
  ctx.fill();

  /* --- 50% band (p25..p75) --- */
  ctx.fillStyle = "rgba(99,150,200,0.28)";
  bandPath("p25", "p75");
  ctx.fill();

  /* --- member plume --- */
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(139,149,161,0.16)";
  members.forEach((m) => {
    const tr = m.traj;
    ctx.beginPath();
    for (let i = 0; i < N && i < tr.length; i++) {
      const xx = x(i), yy = y(tr[i]);
      i === 0 ? ctx.moveTo(xx, yy) : ctx.lineTo(xx, yy);
    }
    ctx.stroke();
  });

  /* --- median, bright + glow --- */
  ctx.save();
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 2.2;
  ctx.lineJoin = "round";
  ctx.beginPath();
  traj.forEach((r, i) => {
    const xx = x(i), yy = y(r.p50);
    i === 0 ? ctx.moveTo(xx, yy) : ctx.lineTo(xx, yy);
  });
  ctx.stroke();
  ctx.restore();

  /* --- start dot at NOW --- */
  ctx.fillStyle = WHITE;
  ctx.beginPath();
  ctx.arc(x(0), y(traj[0].p50), 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = ACCENT;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(x(0), y(traj[0].p50), 6, 0, Math.PI * 2);
  ctx.stroke();
}

/* ---------- boot ---------- */
let lastData = null;

function boot() {
  fetch(DATA_URL, { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((d) => {
      lastData = d;
      fillStrip(d);
      drawFan(d);
    })
    .catch((err) => {
      console.warn("buoycast: live fetch failed,", err.message);
      fillStripFallback();
    });
}

boot();

/* redraw on resize (debounced) */
let rt;
window.addEventListener("resize", () => {
  clearTimeout(rt);
  rt = setTimeout(() => {
    if (lastData) drawFan(lastData);
  }, 160);
});
