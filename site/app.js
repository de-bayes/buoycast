/* Dashboard renderer: data.json (live forecast) + stats.json (validation).
   All charts are plain canvas with a shared axis helper. */
(function () {
  'use strict';

  var C = {
    ink: '#16181d', muted: '#5b6470', faint: '#8a929c', rule: 'rgba(20,24,30,0.09)',
    cyan: '#1257a0', red: '#b3402e', yellow: '#b45309', green: '#2f7d5b', white: '#16181d',
    band1: 'rgba(18,87,160,0.10)', band2: 'rgba(18,87,160,0.20)', dot: 'rgba(18,87,160,0.55)',
    member: 'rgba(120,130,142,0.22)', cross: 'rgba(20,24,30,0.38)', accentSoft: 'rgba(18,87,160,0.07)',
    tipBg: 'rgba(255,255,255,0.97)', tipBorder: 'rgba(20,24,30,0.18)',
  };
  var MONO = '"IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace';

  function chart(canvas, opts) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (!canvas.dataset.baseh) canvas.dataset.baseh = canvas.getAttribute('height');
    var w = canvas.clientWidth, h = parseInt(canvas.dataset.baseh, 10);
    canvas.style.height = h + 'px';
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.font = '10px ' + MONO;
    var padL = opts.padL || 42, padR = opts.padR || 14, padT = opts.padT || 12, padB = opts.padB || 26;
    var pw = w - padL - padR, ph = h - padT - padB;
    var x = function (v) { return padL + ((v - opts.x0) / (opts.x1 - opts.x0)) * pw; };
    var y = function (v) { return padT + ph - ((v - opts.y0) / (opts.y1 - opts.y0)) * ph; };

    ctx.strokeStyle = C.rule;
    ctx.fillStyle = C.faint;
    ctx.lineWidth = 1;
    (opts.yTicks || []).forEach(function (t) {
      ctx.beginPath(); ctx.moveTo(padL, y(t)); ctx.lineTo(padL + pw, y(t)); ctx.stroke();
      ctx.textAlign = 'right';
      ctx.fillText(String(t) + (opts.yUnit || ''), padL - 5, y(t) + 3);
    });
    (opts.xTicks || []).forEach(function (t) {
      var label = typeof t === 'object' ? t.label : String(t);
      var v = typeof t === 'object' ? t.v : t;
      if (opts.xGrid) { ctx.beginPath(); ctx.moveTo(x(v), padT); ctx.lineTo(x(v), padT + ph); ctx.stroke(); }
      ctx.textAlign = 'center';
      ctx.fillText(label, x(v), padT + ph + 16);
    });
    return { ctx: ctx, x: x, y: y, padL: padL, padT: padT, pw: pw, ph: ph };
  }

  function line(g, xs, ys, color, width, dash) {
    g.ctx.strokeStyle = color;
    g.ctx.lineWidth = width || 1.8;
    g.ctx.setLineDash(dash || []);
    g.ctx.lineJoin = 'round';
    g.ctx.beginPath();
    var started = false;
    for (var i = 0; i < xs.length; i++) {
      if (ys[i] === null || ys[i] === undefined) continue;
      started ? g.ctx.lineTo(g.x(xs[i]), g.y(ys[i])) : g.ctx.moveTo(g.x(xs[i]), g.y(ys[i]));
      started = true;
    }
    g.ctx.stroke();
    g.ctx.setLineDash([]);
  }

  function band(g, xs, lo, hi, color) {
    g.ctx.fillStyle = color;
    g.ctx.beginPath();
    xs.forEach(function (v, i) { i ? g.ctx.lineTo(g.x(v), g.y(hi[i])) : g.ctx.moveTo(g.x(v), g.y(hi[i])); });
    for (var i = xs.length - 1; i >= 0; i--) g.ctx.lineTo(g.x(xs[i]), g.y(lo[i]));
    g.ctx.closePath();
    g.ctx.fill();
  }

  function ticksFor(lo, hi, step) {
    var out = [];
    for (var t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(Math.round(t * 10) / 10);
    return out;
  }

  var charts = [];
  function register(fn) { charts.push(fn); fn(); }

  /* floating tooltip box near the crosshair. rows[0] is the header string;
     the rest are [label, value, color] triples. */
  function tooltip(g, hx, rows) {
    var ctx = g.ctx;
    var lines = [rows[0]].concat(rows.slice(1).map(function (r) { return r[0] + '  ' + r[1]; }));
    var bw = 0;
    lines.forEach(function (l) { bw = Math.max(bw, ctx.measureText(l).width); });
    bw += 18;
    var bh = lines.length * 14 + 10;
    var bx = hx + 12; if (bx + bw > g.padL + g.pw) bx = hx - bw - 12;
    if (bx < g.padL + 2) bx = g.padL + 2;
    var by = g.padT + 4;
    ctx.setLineDash([]);
    ctx.fillStyle = C.tipBg;
    ctx.strokeStyle = C.tipBorder;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(bx, by, bw, bh, 5); ctx.fill(); ctx.stroke();
    ctx.textAlign = 'left';
    ctx.fillStyle = C.ink;
    ctx.fillText(lines[0], bx + 9, by + 15);
    for (var i = 1; i < rows.length; i++) {
      ctx.fillStyle = rows[i][2] || C.muted;
      ctx.fillText(rows[i][0] + '  ' + rows[i][1], bx + 9, by + 15 + i * 14);
    }
  }

  /* generic interactive multi-series line chart with a hover crosshair that
     snaps to the nearest x and reads every series out into a tooltip. */
  function lineChart(canvasId, cfg) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var hoverPx = null;
    function draw() {
      var g = chart(canvas, {
        x0: cfg.x0, x1: cfg.x1, y0: cfg.y0, y1: cfg.y1, yTicks: cfg.yTicks,
        yUnit: cfg.yUnit, xTicks: cfg.xTicks, xGrid: cfg.xGrid, padR: cfg.padR, padL: cfg.padL,
      });
      (cfg.bands || []).forEach(function (b) { band(g, cfg.xs, b.lo, b.hi, b.color); });
      (cfg.refLines || []).forEach(function (r) { line(g, [cfg.x0, cfg.x1], [r.y, r.y], r.color, 0.8, [4, 4]); });
      cfg.series.forEach(function (s) { line(g, cfg.xs, s.ys, s.color, s.width || 1.8, s.dash); });
      if (cfg.note) { g.ctx.fillStyle = C.muted; g.ctx.textAlign = 'left'; g.ctx.fillText(cfg.note, g.padL + 4, g.padT + 2); }
      if (hoverPx !== null) {
        var idx = 0, best = Infinity;
        for (var i = 0; i < cfg.xs.length; i++) {
          var d = Math.abs(g.x(cfg.xs[i]) - hoverPx);
          if (d < best) { best = d; idx = i; }
        }
        var hx = g.x(cfg.xs[idx]);
        g.ctx.strokeStyle = C.cross; g.ctx.lineWidth = 1; g.ctx.setLineDash([]);
        g.ctx.beginPath(); g.ctx.moveTo(hx, g.padT); g.ctx.lineTo(hx, g.padT + g.ph); g.ctx.stroke();
        var rows = [cfg.xLabel ? cfg.xLabel(cfg.xs[idx]) : String(cfg.xs[idx])];
        cfg.series.forEach(function (s) {
          if (s.faint || s.ys[idx] == null) return;
          g.ctx.fillStyle = s.color;
          g.ctx.beginPath(); g.ctx.arc(hx, g.y(s.ys[idx]), 3, 0, Math.PI * 2); g.ctx.fill();
          rows.push([s.name, cfg.fmt ? cfg.fmt(s.ys[idx]) : s.ys[idx].toFixed(2), s.color]);
        });
        tooltip(g, hx, rows);
      }
    }
    function move(e) {
      var rect = canvas.getBoundingClientRect();
      hoverPx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
      window.requestAnimationFrame(draw);
    }
    canvas.addEventListener('mousemove', move);
    canvas.addEventListener('touchmove', move);
    canvas.addEventListener('mouseleave', function () { hoverPx = null; window.requestAnimationFrame(draw); });
    register(draw);
  }

  // DATA_BASE lets the static site live on one host (e.g. Vercel) while the
  // VPS that computes the forecast serves the json from another origin;
  // empty means same origin. Set window.DATA_BASE before this script loads.
  var DATA_BASE = window.DATA_BASE || '';
  Promise.all([
    fetch(DATA_BASE + '/data.json').then(function (r) { return r.json(); }),
    fetch(DATA_BASE + '/stats.json').then(function (r) { return r.json(); }),
  ]).then(function (res) {
    var data = res[0], stats = res[1];
    var gen = new Date(data.generated_utc);
    document.getElementById('stamp').textContent =
      'UPDATED ' + gen.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).toUpperCase();

    /* chips */
    var h24 = null, h168 = null;
    stats.horizons.forEach(function (s) { if (s.h === 24) h24 = s; if (s.h === 168) h168 = s; });
    var chips = [
      ['+24H TEST MAE', h24.mae.toFixed(2) + '°F'],
      ['+7D TEST MAE', h168.mae.toFixed(2) + '°F'],
      ['SKILL VS PERSISTENCE +7D', Math.round((1 - h168.mae / h168.mae_persistence) * 100) + '%'],
      ['90% BAND COVERAGE +24H', Math.round(h24.cover90 * 100) + '%'],
      ['TRAINING ROWS', (stats.n_train / 1000).toFixed(0) + 'k'],
      ['FEATURES', String(stats.n_features)],
    ];
    if (stats.backtest) {
      chips.splice(4, 0, ['BACKTESTED PAIRS', (stats.backtest.total_pairs / 1000).toFixed(0) + 'k']);
    }
    var cwrap = document.getElementById('chips');
    chips.forEach(function (c) {
      var d = document.createElement('div');
      d.className = 'chip';
      d.innerHTML = '<span>' + c[0] + '</span><b>' + c[1] + '</b>';
      cwrap.appendChild(d);
    });

    /* now card */
    document.getElementById('now-wtmp').textContent = data.now.wtmp_f.toFixed(1) + '°F';
    var grid = document.getElementById('now-grid');
    [['AIR', data.now.atmp_f.toFixed(1) + '°F'], ['WAVES', data.now.wvht_ft + ' ft'],
     ['WIND', data.now.wspd_kt + ' kt'], ['GUSTS', data.now.gst_kt + ' kt']].forEach(function (kv) {
      var d = document.createElement('div');
      d.innerHTML = '<span>' + kv[0] + '</span><b>' + kv[1] + '</b>';
      grid.appendChild(d);
    });

    /* fan, with a hover crosshair and a play-once intro: the 34 simulated
       futures stream out from the live reading, then the calibrated band
       materializes around them, then the median draws */
    var fanCanvas = document.getElementById('fan');
    var fanHover = null;
    var X0 = 0, X1 = 168;
    var fanT0 = null, FAN_INTRO = 2400;
    function easeO(p) { p = Math.max(0, Math.min(1, p)); return 1 - Math.pow(1 - p, 3); }
    function drawFan() {
      if (fanT0 === null) fanT0 = performance.now();
      var ip = Math.min(1, (performance.now() - fanT0) / FAN_INTRO);
      var memP = easeO(ip / 0.55);                       // members draw first
      var bandA = easeO((ip - 0.35) / 0.4);              // bands fade in
      var medP = easeO((ip - 0.4) / 0.6);                // median draws last
      var tr = data.trajectory;
      var hs = tr.map(function (p) { return p.h; });
      var lo = Infinity, hi = -Infinity;
      tr.forEach(function (p) { lo = Math.min(lo, p.p05); hi = Math.max(hi, p.p95); });
      lo = Math.floor(lo - 0.5); hi = Math.ceil(hi + 0.5);
      var xt = [];
      tr.forEach(function (p) {
        var d = new Date(p.t);
        if (d.getUTCHours() === 0) {
          xt.push({ v: p.h, label: d.toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric', timeZone: 'UTC' }) });
        }
      });
      var g = chart(fanCanvas,
        { x0: X0, x1: X1, y0: lo, y1: hi, yTicks: ticksFor(lo, hi, 1), yUnit: '°', xTicks: xt, xGrid: true, padR: 64 });

      // forecast fan
      if (bandA > 0) {
        g.ctx.globalAlpha = bandA;
        band(g, hs, tr.map(function (p) { return p.p05; }), tr.map(function (p) { return p.p95; }), C.band1);
        band(g, hs, tr.map(function (p) { return p.p25; }), tr.map(function (p) { return p.p75; }), C.band2);
        g.ctx.globalAlpha = 1;
      }
      // ensemble spaghetti: one faint line per simulated future, clipped to
      // the intro's progress so they visibly stream outward from the dot
      var nPts = Math.max(2, Math.round(memP * hs.length));
      (data.members || []).forEach(function (m) {
        line(g, hs.slice(0, nPts), m.traj.slice(0, nPts), C.member, 0.8);
      });
      if (medP > 0) {
        var nMed = Math.max(2, Math.round(medP * hs.length));
        line(g, hs.slice(0, nMed), tr.slice(0, nMed).map(function (p) { return p.p50; }), C.cyan, 2.2);
      }
      if (ip < 1 && fanHover === null) window.requestAnimationFrame(drawFan);

      // now anchor dot
      g.ctx.fillStyle = C.white;
      g.ctx.beginPath();
      g.ctx.arc(g.x(1), g.y(tr[0].p50), 3.5, 0, Math.PI * 2);
      g.ctx.fill();
      g.ctx.textAlign = 'left';
      g.ctx.fillText('now ' + data.now.wtmp_f.toFixed(1) + '°', g.x(1) + 7, g.y(tr[0].p50) - 9);

      // right-edge quantile labels
      var end = tr[tr.length - 1];
      [['p95', C.faint, 'P95'], ['p50', C.cyan, 'P50'], ['p05', C.faint, 'P5']].forEach(function (kq) {
        g.ctx.fillStyle = kq[1];
        g.ctx.textAlign = 'left';
        g.ctx.fillText(kq[2] + ' ' + end[kq[0]].toFixed(1) + '°', g.x(168) + 5, g.y(end[kq[0]]) + 3);
      });

      if (fanHover !== null && fanHover >= 1 && fanHover <= tr.length) {
        var p = tr[fanHover - 1];
        var cx = g.x(p.h);
        g.ctx.strokeStyle = 'rgba(18,87,160,0.75)';
        g.ctx.lineWidth = 1;
        g.ctx.beginPath();
        g.ctx.moveTo(cx, g.padT);
        g.ctx.lineTo(cx, g.padT + g.ph);
        g.ctx.stroke();
        [['p05', 1.5], ['p25', 2], ['p50', 3], ['p75', 2], ['p95', 1.5]].forEach(function (kq) {
          g.ctx.fillStyle = kq[0] === 'p50' ? C.white : C.cyan;
          g.ctx.beginPath();
          g.ctx.arc(cx, g.y(p[kq[0]]), kq[1], 0, Math.PI * 2);
          g.ctx.fill();
        });
        var d = new Date(p.t);
        var lines = [
          d.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric' }) + ' · +' + p.h + 'h',
          'median  ' + p.p50.toFixed(1) + '°F',
          'likely  ' + p.p25.toFixed(1) + ' - ' + p.p75.toFixed(1) + '°  (50%)',
          'range   ' + p.p05.toFixed(1) + ' - ' + p.p95.toFixed(1) + '°  (90%)',
          'band    ±' + ((p.p95 - p.p05) / 2).toFixed(1) + '°',
        ];
        if (data.members && data.members.length) {
          var mv = data.members.map(function (m) { return m.traj[p.h - 1]; });
          lines.push('members ' + Math.min.apply(null, mv).toFixed(1) + ' - ' + Math.max.apply(null, mv).toFixed(1) + '°  (' + data.members.length + ')');
        }
        var bw = 0;
        lines.forEach(function (l) { bw = Math.max(bw, g.ctx.measureText(l).width); });
        bw += 20;
        var bh = lines.length * 15 + 12;
        var bx = cx + 12;
        if (bx + bw > g.padL + g.pw) bx = cx - bw - 12;
        var by = g.padT + 6;
        g.ctx.fillStyle = C.tipBg;
        g.ctx.strokeStyle = C.cyan;
        g.ctx.beginPath();
        g.ctx.roundRect(bx, by, bw, bh, 5);
        g.ctx.fill();
        g.ctx.stroke();
        g.ctx.textAlign = 'left';
        lines.forEach(function (l, i) {
          g.ctx.fillStyle = i === 0 ? C.cyan : i === 1 ? C.ink : C.muted;
          g.ctx.fillText(l, bx + 10, by + 18 + i * 15);
        });
      }
    }
    register(drawFan);
    function fanMove(e) {
      var rect = fanCanvas.getBoundingClientRect();
      var clientX = e.touches ? e.touches[0].clientX : e.clientX;
      var frac = (clientX - rect.left - 42) / (rect.width - 42 - 64);
      var h = Math.round(X0 + frac * (X1 - X0));
      h = Math.max(1, Math.min(X1, h));
      if (h !== fanHover) { fanHover = h; window.requestAnimationFrame(drawFan); }
    }
    fanCanvas.addEventListener('mousemove', fanMove);
    fanCanvas.addEventListener('touchmove', fanMove);
    fanCanvas.addEventListener('mouseleave', function () { fanHover = null; window.requestAnimationFrame(drawFan); });

    /* daily digest */
    var dg = document.getElementById('digest');
    data.daily.forEach(function (d) {
      var el = document.createElement('div');
      el.className = 'digest__day';
      el.innerHTML = '<span class="digest__label">' + d.label.toUpperCase() + '</span>' +
        '<b>' + d.p50.toFixed(0) + '°</b>' +
        '<span class="digest__range">' + d.p05.toFixed(0) + '-' + d.p95.toFixed(0) + '°</span>';
      dg.appendChild(el);
    });

    /* uncertainty decomposition (interactive): irreducible vs weather-model */
    if (data.uncertainty) {
      var un = data.uncertainty;
      var unMax = 0;
      un.forEach(function (u) { unMax = Math.max(unMax, u.irreducible, u.weather); });
      unMax = Math.ceil((unMax + 0.3) * 2) / 2;
      lineChart('uncertainty', {
        xs: un.map(function (u) { return u.h; }), x0: 1, x1: 168, y0: 0, y1: unMax,
        yTicks: ticksFor(0, unMax, 1), yUnit: '°',
        xTicks: [24, 48, 72, 96, 120, 144, 168].map(function (v) { return { v: v, label: v + 'h' }; }),
        series: [
          { name: 'irreducible (perfect weather)', ys: un.map(function (u) { return u.irreducible; }), color: C.faint, width: 2 },
          { name: 'weather-model disagreement', ys: un.map(function (u) { return u.weather; }), color: C.cyan, width: 2 },
        ],
        fmt: function (v) { return '±' + v.toFixed(2) + '°'; }, xLabel: function (v) { return '+' + v + 'h lead'; },
        note: 'irreducible (gray) · weather-model disagreement (cyan) · 90% half-widths',
      });
    }

    /* skill curve (interactive) */
    (function () {
      var hsx = stats.horizons.map(function (s) { return s.h; });
      var maxY = Math.ceil(Math.max.apply(null, stats.horizons.map(function (s) { return s.mae_persistence; })) + 0.5);
      lineChart('skill', {
        xs: hsx, x0: 0, x1: 168, y0: 0, y1: maxY, yTicks: ticksFor(0, maxY, 1), yUnit: '°',
        xTicks: [24, 48, 72, 96, 120, 144, 168].map(function (v) { return { v: v, label: v + 'h' }; }),
        series: [
          { name: 'persistence', ys: stats.horizons.map(function (s) { return s.mae_persistence; }), color: C.faint, width: 1.6, dash: [5, 4] },
          { name: 'model MAE', ys: stats.horizons.map(function (s) { return s.mae; }), color: C.cyan, width: 2.2 },
          { name: 'model P90 |err|', ys: stats.horizons.map(function (s) { return s.p90_abs_err; }), color: C.cyan, width: 1, dash: [2, 3] },
        ],
        fmt: function (v) { return v.toFixed(2) + '°'; }, xLabel: function (v) { return '+' + v + 'h lead'; },
        note: 'persistence (dashed) · model MAE (solid) · model P90 |err| (dotted)',
      });
    })();

    /* coverage (interactive) */
    (function () {
      var hsx = stats.horizons.map(function (s) { return s.h; });
      lineChart('coverage', {
        xs: hsx, x0: 0, x1: 168, y0: 0, y1: 1, yTicks: [0, 0.25, 0.5, 0.75, 0.9, 1],
        xTicks: [24, 48, 72, 96, 120, 144, 168].map(function (v) { return { v: v, label: v + 'h' }; }),
        refLines: [{ y: 0.9, color: C.cyan }, { y: 0.5, color: C.yellow }],
        series: [
          { name: '90% band', ys: stats.horizons.map(function (s) { return s.cover90; }), color: C.cyan, width: 2 },
          { name: '50% band', ys: stats.horizons.map(function (s) { return s.cover50; }), color: C.yellow, width: 2 },
        ],
        fmt: function (v) { return Math.round(v * 100) + '%'; }, xLabel: function (v) { return '+' + v + 'h lead'; },
      });
    })();

    /* hindcast (interactive) */
    (function () {
      var hc = stats.hindcast24;
      var n = hc.time.length;
      var xs = hc.time.map(function (_, i) { return i; });
      var lo = Math.floor(Math.min.apply(null, hc.p05) - 1);
      var hi = Math.ceil(Math.max.apply(null, hc.p95) + 1);
      var xt = [];
      hc.time.forEach(function (t, i) {
        var d = new Date(t);
        if (d.getUTCDate() % 7 === 0 && d.getUTCHours() === 0) {
          xt.push({ v: i, label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }) });
        }
      });
      lineChart('hindcast', {
        xs: xs, x0: 0, x1: n - 1, y0: lo, y1: hi, yTicks: ticksFor(lo, hi, 2), yUnit: '°', xTicks: xt, xGrid: true,
        bands: [{ lo: hc.p05, hi: hc.p95, color: C.band1 }],
        series: [
          { name: '+24h median', ys: hc.p50, color: C.cyan, width: 1.4 },
          { name: 'actual', ys: hc.actual, color: C.white, width: 1.4 },
        ],
        fmt: function (v) { return v.toFixed(1) + '°'; },
        xLabel: function (i) { return new Date(hc.time[i]).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', timeZone: 'UTC' }); },
        note: 'actual (white) · +24h median (cyan) · 90% band (shaded)',
      });
    })();

    /* residual histogram */
    register(function () {
      var r = stats.residuals24;
      var maxC = Math.max.apply(null, r.counts);
      var g = chart(document.getElementById('residuals'),
        { x0: r.edges[0], x1: r.edges[r.edges.length - 1], y0: 0, y1: maxC * 1.1,
          yTicks: [], xTicks: [-3, -2, -1, 0, 1, 2, 3].map(function (v) { return { v: v, label: v + '°' }; }) });
      r.counts.forEach(function (c, i) {
        var x0 = g.x(r.edges[i]), x1 = g.x(r.edges[i + 1]);
        var bh = (c / (maxC * 1.1)) * g.ph;
        g.ctx.fillStyle = r.edges[i] >= -0.25 && r.edges[i + 1] <= 0.25 ? C.cyan : 'rgba(18,87,160,0.40)';
        g.ctx.fillRect(x0 + 0.5, g.padT + g.ph - bh, x1 - x0 - 1, bh);
      });
      line(g, [0, 0], [0, maxC * 1.1], C.white, 0.8, [3, 3]);
    });

    /* scatter */
    register(function () {
      var pts = stats.scatter24;
      var lo = Infinity, hi = -Infinity;
      pts.forEach(function (p) { lo = Math.min(lo, p[0], p[1]); hi = Math.max(hi, p[0], p[1]); });
      lo = Math.floor(lo - 1); hi = Math.ceil(hi + 1);
      var t5 = ticksFor(lo, hi, 5);
      var g = chart(document.getElementById('scatter'),
        { x0: lo, x1: hi, y0: lo, y1: hi, yTicks: t5, yUnit: '°',
          xTicks: t5.map(function (v) { return { v: v, label: v + '°' }; }) });
      line(g, [lo, hi], [lo, hi], C.faint, 1, [4, 4]);
      g.ctx.fillStyle = C.dot;
      pts.forEach(function (p) {
        g.ctx.beginPath();
        g.ctx.arc(g.x(p[0]), g.y(p[1]), 2, 0, Math.PI * 2);
        g.ctx.fill();
      });
    });

    /* importance */
    register(function () {
      var canvas = document.getElementById('importance');
      var imp = stats.importance;
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (!canvas.dataset.baseh) canvas.dataset.baseh = canvas.getAttribute('height');
      var w = canvas.clientWidth, hgt = parseInt(canvas.dataset.baseh, 10);
      canvas.style.height = hgt + 'px';
      canvas.width = w * dpr; canvas.height = hgt * dpr;
      var ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = '10px ' + MONO;
      var padL = 130, padR = 40;
      var rowH = (hgt - 10) / imp.length;
      var maxV = imp[0].value;
      imp.forEach(function (f, i) {
        var yy = 5 + i * rowH;
        ctx.fillStyle = C.muted;
        ctx.textAlign = 'right';
        ctx.fillText(f.name, padL - 8, yy + rowH / 2 + 3);
        ctx.fillStyle = f.name.indexOf('fut_') === 0 ? C.green : C.cyan;
        var bw = ((w - padL - padR) * f.value) / maxV;
        ctx.fillRect(padL, yy + 2, bw, rowH - 5);
        ctx.fillStyle = C.faint;
        ctx.textAlign = 'left';
        ctx.fillText(f.value.toFixed(2), padL + bw + 5, yy + rowH / 2 + 3);
      });
      ctx.fillStyle = C.muted;
      ctx.textAlign = 'left';
    });

    /* backtest card (interactive) */
    if (stats.backtest) {
      var bt = stats.backtest;
      var i24 = bt.horizons.indexOf(24);
      var iEnd = bt.horizons.length - 1;
      document.getElementById('backtest-card').hidden = false;
      var btMax = Math.ceil(Math.max.apply(null, bt.mean_mae_persist) + 0.5);
      var foldSeries = bt.folds.map(function (f) {
        return { name: f.name, ys: f.mae, color: 'rgba(18,87,160,0.22)', width: 1, faint: true };
      });
      lineChart('backtest-chart', {
        xs: bt.horizons, x0: 0, x1: 168, y0: 0, y1: btMax, yTicks: ticksFor(0, btMax, 1), yUnit: '°',
        xTicks: [24, 48, 72, 96, 120, 144, 168].map(function (v) { return { v: v, label: v + 'h' }; }),
        series: foldSeries.concat([
          { name: 'persistence (all seasons)', ys: bt.mean_mae_persist, color: C.faint, width: 1.8, dash: [5, 4] },
          { name: 'model (all seasons)', ys: bt.mean_mae, color: C.cyan, width: 2.6 },
        ]),
        fmt: function (v) { return v.toFixed(2) + '°'; }, xLabel: function (v) { return '+' + v + 'h lead'; },
        note: bt.folds.length + ' seasons (faint) · all-season mean model (solid) vs persistence (dashed)',
      });
      document.getElementById('backtest-cap').textContent =
        bt.total_pairs.toLocaleString() + ' forecast/outcome pairs across ' + bt.folds.length +
        ' season-end windows (' + bt.folds.map(function (f) { return f.name; }).join(', ') +
        '), each fold trained only on data ending 8 days before its window. All-season mean MAE: ' +
        bt.mean_mae[i24].toFixed(2) + '°F at +24h and ' + bt.mean_mae[iEnd].toFixed(2) +
        '°F at +168h, vs persistence at ' + bt.mean_mae_persist[i24].toFixed(2) + ' and ' +
        bt.mean_mae_persist[iEnd].toFixed(2) + '. Mean 90% band coverage ' +
        Math.round(bt.mean_cover90.reduce(function (a, b) { return a + b; }, 0) / bt.mean_cover90.length * 100) + '%.';
    }

    /* driver study (interactive): paired bars + window sweep */
    if (stats.driver) {
      var dv = stats.driver;

      /* paired horizontal bars: |corr| of next-24h water change with each
         driver, measured over the past window vs the forecast window */
      (function () {
        var canvas = document.getElementById('driver-bars');
        if (!canvas) return;
        var rowsD = dv.drivers.slice().reverse();
        var maxV = 0;
        rowsD.forEach(function (d) { maxV = Math.max(maxV, Math.abs(d.past), Math.abs(d.future)); });
        maxV = Math.ceil(maxV * 10) / 10;
        var hoverRow = null;
        function draw() {
          var dpr = Math.min(window.devicePixelRatio || 1, 2);
          if (!canvas.dataset.baseh) canvas.dataset.baseh = canvas.getAttribute('height');
          var w = canvas.clientWidth, hgt = parseInt(canvas.dataset.baseh, 10);
          canvas.style.height = hgt + 'px'; canvas.width = w * dpr; canvas.height = hgt * dpr;
          var ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.font = '10px ' + MONO;
          var padL = 150, padR = 46, padT = 8, padB = 18;
          var plotW = w - padL - padR, rowH = (hgt - padT - padB) / rowsD.length;
          [0, 0.1, 0.2, 0.3].forEach(function (t) {
            if (t > maxV) return;
            var xx = padL + (t / maxV) * plotW;
            ctx.strokeStyle = C.rule; ctx.lineWidth = 1; ctx.beginPath();
            ctx.moveTo(xx, padT); ctx.lineTo(xx, padT + rowH * rowsD.length); ctx.stroke();
            ctx.fillStyle = C.faint; ctx.textAlign = 'center'; ctx.fillText(t.toFixed(1), xx, hgt - 5);
          });
          rowsD.forEach(function (d, i) {
            var yy = padT + i * rowH;
            if (i === hoverRow) { ctx.fillStyle = C.accentSoft; ctx.fillRect(0, yy, w, rowH); }
            ctx.fillStyle = i === hoverRow ? C.ink : C.muted; ctx.textAlign = 'right';
            ctx.fillText(d.name, padL - 8, yy + rowH / 2 + 3);
            var pb = (Math.abs(d.past) / maxV) * plotW, fb = (Math.abs(d.future) / maxV) * plotW;
            ctx.fillStyle = C.faint; ctx.fillRect(padL, yy + rowH * 0.5 + 1, pb, rowH * 0.34);
            ctx.fillStyle = C.cyan; ctx.fillRect(padL, yy + rowH * 0.15, fb, rowH * 0.34);
            if (i === hoverRow) {
              ctx.fillStyle = C.cyan; ctx.textAlign = 'left';
              ctx.fillText(d.future.toFixed(2), padL + fb + 5, yy + rowH * 0.32 + 3);
              ctx.fillStyle = C.faint;
              ctx.fillText(d.past.toFixed(2), padL + pb + 5, yy + rowH * 0.67 + 3);
            }
          });
          ctx.fillStyle = C.cyan; ctx.textAlign = 'left'; ctx.fillText('forecast window', padL + 2, padT + 0);
          ctx.fillStyle = C.faint; ctx.fillText('past 24h', padL + 2, padT + rowH * rowsD.length - 1);
        }
        canvas.addEventListener('mousemove', function (e) {
          var rect = canvas.getBoundingClientRect();
          var yrel = e.clientY - rect.top - 8;
          var rowH = (parseInt(canvas.dataset.baseh, 10) - 26) / rowsD.length;
          var r = Math.floor(yrel / rowH);
          hoverRow = (r >= 0 && r < rowsD.length) ? r : null;
          window.requestAnimationFrame(draw);
        });
        canvas.addEventListener('mouseleave', function () { hoverRow = null; window.requestAnimationFrame(draw); });
        register(draw);
      })();

      /* window sweep: how |corr| builds with forecast-window length */
      (function () {
        var palette = [C.cyan, C.red, C.yellow, C.green];
        var keys = Object.keys(dv.sweep);
        lineChart('driver-sweep', {
          xs: dv.windows, x0: dv.windows[0], x1: dv.windows[dv.windows.length - 1],
          y0: 0, y1: Math.ceil(Math.max.apply(null, keys.map(function (k) { return Math.max.apply(null, dv.sweep[k].map(Math.abs)); })) * 10) / 10,
          yTicks: [0, 0.1, 0.2, 0.3, 0.4], xGrid: true,
          xTicks: dv.windows.map(function (v) { return { v: v, label: v + 'h' }; }),
          series: keys.map(function (k, i) { return { name: k, ys: dv.sweep[k].map(Math.abs), color: palette[i % palette.length], width: 2 }; }),
          fmt: function (v) { return v.toFixed(2); }, xLabel: function (v) { return v + 'h window'; },
        });
      })();
    }

    /* validation table */
    var tbl = document.getElementById('stat-table');
    var head = '<tr><th>lead</th><th>MAE</th><th>persistence</th><th>skill</th><th>RMSE</th><th>bias</th><th>P90 |err|</th><th>90% width</th><th>cover 90/50</th><th>n</th></tr>';
    tbl.innerHTML = head + stats.horizons.map(function (s) {
      var skill = Math.round((1 - s.mae / s.mae_persistence) * 100);
      return '<tr><td>+' + s.h + 'h</td><td>' + s.mae.toFixed(2) + '</td><td>' + s.mae_persistence.toFixed(2) +
        '</td><td>' + (skill >= 0 ? '+' : '') + skill + '%</td><td>' + s.rmse.toFixed(2) + '</td><td>' + s.bias.toFixed(2) +
        '</td><td>' + s.p90_abs_err.toFixed(2) + '</td><td>' + s.band90_width.toFixed(1) +
        '</td><td>' + Math.round(s.cover90 * 100) + '/' + Math.round(s.cover50 * 100) + '</td><td>' + s.n + '</td></tr>';
    }).join('');

    window.addEventListener('resize', function () { charts.forEach(function (fn) { fn(); }); });
  }).catch(function (e) {
    document.getElementById('stamp').textContent = 'DATA UNAVAILABLE, RUN publish.py';
  });
})();
