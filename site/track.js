/* Track record renderer: verify.json (live scorecard of published forecasts).
   Self-contained canvas charts; the same axis/line/band scaffolding and palette
   as app.js (which keeps its helpers inside an IIFE, so they are replicated
   here rather than imported). Guards every field: verify.json may be thin on
   day one, and the page must render calmly when it is. */
(function () {
  'use strict';

  var C = {
    ink: '#16181d', muted: '#5b6470', faint: '#8a929c', rule: 'rgba(20,24,30,0.09)',
    cyan: '#1257a0', yellow: '#b45309', green: '#2f7d5b', white: '#16181d',
    band1: 'rgba(18,87,160,0.10)', band2: 'rgba(18,87,160,0.20)',
    dot: 'rgba(18,87,160,0.55)', hollow: 'rgba(138,146,156,0.85)',
    cross: 'rgba(20,24,30,0.38)', accentSoft: 'rgba(18,87,160,0.07)',
    tipBg: 'rgba(255,255,255,0.97)', tipBorder: 'rgba(20,24,30,0.18)',
  };
  var MONO = '"IBM Plex Mono", Menlo, monospace';

  /* ---- shared canvas scaffolding (mirrors app.js) ---- */
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

  var charts = [];
  function register(fn) { charts.push(fn); fn(); }

  /* ---- small helpers ---- */
  function num(v, d) { return (typeof v === 'number' && isFinite(v)) ? v : null; }
  function pct(v) { return v == null ? '—' : Math.round(v * 100) + '%'; }
  function f1(v) { return v == null ? '—' : v.toFixed(1); }
  function f2(v) { return v == null ? '—' : v.toFixed(2); }
  function fmtDate(iso, withTime) {
    var d = new Date(iso);
    if (isNaN(d)) return '—';
    var o = { month: 'short', day: 'numeric', year: 'numeric' };
    if (withTime) { o = { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', timeZone: 'UTC' }; }
    return d.toLocaleString('en-US', o);
  }

  var DATA_BASE = window.DATA_BASE || '';

  fetch(DATA_BASE + '/verify.json').then(function (r) { return r.json(); }).then(function (v) {
    render(v || {});
  }).catch(function () {
    var s = document.getElementById('tr-stamp');
    if (s) s.textContent = 'DATA UNAVAILABLE, RUN verify.py';
    showEmpty('Tracking data is not available yet — check back once verify.py has run.');
  });

  function showEmpty(msg) {
    var sec = document.getElementById('sec-empty');
    if (!sec) return;
    sec.hidden = false;
    var m = document.getElementById('tr-empty-msg');
    if (m && msg) m.textContent = msg;
  }

  function render(v) {
    var stamp = document.getElementById('tr-stamp');
    if (stamp) {
      var gen = v.generated_utc ? new Date(v.generated_utc) : null;
      stamp.textContent = (gen && !isNaN(gen))
        ? 'UPDATED ' + gen.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).toUpperCase()
        : 'TRACKING';
    }

    /* intro meta: tracking_since + the live/hindcast split */
    var meta = document.getElementById('tr-intro-meta');
    if (meta) {
      var nF = num(v.n_forecasts) || 0;
      if (nF > 0) {
        var parts = ['Tracking since ' + fmtDate(v.tracking_since) + '.',
          nF + ' distinct forecasts scored in the rolling ' + (v.window_days || 30) + '-day window'];
        var live = num(v.n_live), hind = num(v.n_hindcast);
        if (live != null || hind != null) {
          parts.push('— ' + (live || 0) + ' genuinely published, ' + (hind || 0) + ' reconstructed to seed the page on day one.');
        } else { parts[parts.length - 1] += '.'; }
        meta.textContent = parts.join(' ');
      } else {
        meta.textContent = 'Live tracking has just begun. The multi-season backtest below already stands; the live numbers fill in as forecasts resolve.';
      }
    }

    var recent = Array.isArray(v.recent24) ? v.recent24 : [];
    var byLead = Array.isArray(v.by_lead) ? v.by_lead : [];
    var thin = (num(v.n_forecasts) || 0) === 0 || recent.length === 0;

    headlineCards(v.headline || {});
    if (recent.length) { recentChart(recent); }
    leadCharts(byLead);
    leadTable(byLead);
    calibChart(byLead, v.band_scale);
    bandScaleNote(v.band_scale, v.backtest || null, byLead);

    if (thin) {
      showEmpty('Live tracking just started — check back as forecasts resolve. The skill-by-lead and calibration readouts below draw on the multi-season backtest in the meantime.');
    }

    window.addEventListener('resize', function () { charts.forEach(function (fn) { fn(); }); });
  }

  /* ---- 01. headline stat cards (the .headline-row pattern from index.html) ---- */
  function headlineCards(h) {
    var wrap = document.getElementById('tr-headline');
    if (!wrap) return;
    var cards = [];
    var mae = num(h.mae_f);
    cards.push(['+24h median error', mae != null ? f2(mae) + '<em>°F</em>' : '—',
      mae != null ? 'vs ' + f2(num(h.mae_persist_f)) + '°F for persistence' : 'awaiting resolved forecasts']);

    var skill = num(h.skill_pct);
    cards.push(['Skill vs persistence', skill != null ? (skill >= 0 ? '+' : '') + skill + '<em>%</em>' : '—',
      skill != null ? (skill >= 0 ? skill + '% better than assuming no change' : 'level with no-change at this lead') : 'awaiting resolved forecasts']);

    var c90 = num(h.cover90);
    cards.push(['90% band coverage', c90 != null ? pct(c90) : '—',
      c90 != null ? 'target 90% · ' + coverWord(c90) : 'awaiting resolved forecasts']);

    wrap.innerHTML = cards.map(function (c) {
      return '<div><span>' + c[0] + '</span><b>' + c[1] + '</b><span style="margin-top:.5rem;text-transform:none;letter-spacing:.02em;color:var(--muted)">' + c[2] + '</span></div>';
    }).join('');

    var note = document.getElementById('tr-headline-note');
    if (note && num(h.bias_f) != null) {
      var b = num(h.bias_f);
      var dir = Math.abs(b) < 0.05 ? 'essentially unbiased' :
        (b > 0 ? 'running ' + f2(Math.abs(b)) + '°F warm' : 'running ' + f2(Math.abs(b)) + '°F cool');
      note.textContent = note.textContent + ' On the resolved +24h forecasts the median is ' + dir + ' (mean signed error ' + (b >= 0 ? '+' : '') + f2(b) + '°F).';
    }
  }
  function coverWord(c) {
    if (c >= 0.88) return c <= 0.95 ? 'right on target' : 'a touch conservative';
    if (c >= 0.80) return 'running a little narrow';
    return 'narrower than claimed';
  }

  /* ---- 02. recent +24h calls vs actual ---- */
  function recentChart(recent) {
    var canvas = document.getElementById('tr-recent');
    if (!canvas) return;
    var xs = recent.map(function (_, i) { return i; });
    var n = recent.length;
    var p05 = recent.map(function (r) { return num(r.p05); });
    var p50 = recent.map(function (r) { return num(r.p50); });
    var p95 = recent.map(function (r) { return num(r.p95); });
    var act = recent.map(function (r) { return num(r.actual); });
    var isLive = recent.map(function (r) { return r.origin !== 'hindcast'; });
    var times = recent.map(function (r) { return r.valid; });

    var lo = Infinity, hi = -Infinity;
    recent.forEach(function (r) {
      [r.p05, r.p95, r.actual].forEach(function (val) {
        if (typeof val === 'number' && isFinite(val)) { lo = Math.min(lo, val); hi = Math.max(hi, val); }
      });
    });
    if (!isFinite(lo)) { lo = 50; hi = 70; }
    lo = Math.floor(lo - 1); hi = Math.ceil(hi + 1);

    var xt = [];
    times.forEach(function (t, i) {
      var d = new Date(t);
      if (isNaN(d)) return;
      if (d.getUTCHours() === 0 && (i === 0 || new Date(times[i - 1]).getUTCDate() !== d.getUTCDate())) {
        xt.push({ v: i, label: d.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', timeZone: 'UTC' }) });
      }
    });

    /* split actual into live vs hindcast segments so we can draw hindcast
       dashed/hollow and live solid */
    var liveAct = act.map(function (a, i) { return isLive[i] ? a : null; });
    var hindAct = act.map(function (a, i) { return isLive[i] ? null : a; });
    var firstLive = isLive.indexOf(true);

    var hoverPx = null;
    function draw() {
      var g = chart(canvas, {
        x0: 0, x1: Math.max(1, n - 1), y0: lo, y1: hi,
        yTicks: ticksFor(lo, hi, 2), yUnit: '°', xTicks: xt, xGrid: true, padR: 14,
      });
      band(g, xs, p05, p95, C.band1);
      /* median: faint where hindcast, solid where live */
      line(g, xs, p50, C.cyan, 1.6);
      /* actual: hindcast dashed light, live solid dark */
      line(g, xs, hindAct, C.hollow, 1.4, [4, 3]);
      line(g, xs, liveAct, C.white, 1.6);

      /* a faint vertical marker where the live record begins */
      if (firstLive > 0) {
        g.ctx.strokeStyle = C.rule; g.ctx.lineWidth = 1; g.ctx.setLineDash([2, 3]);
        g.ctx.beginPath(); g.ctx.moveTo(g.x(firstLive), g.padT); g.ctx.lineTo(g.x(firstLive), g.padT + g.ph); g.ctx.stroke();
        g.ctx.setLineDash([]);
        g.ctx.fillStyle = C.faint; g.ctx.textAlign = 'left';
        g.ctx.fillText('live →', g.x(firstLive) + 4, g.padT + 10);
      }

      g.ctx.fillStyle = C.muted; g.ctx.textAlign = 'left';
      g.ctx.fillText('actual (dark) · +24h median (blue) · 90% band (shaded) · hindcast (dashed)', g.padL + 4, g.padT + 2);

      if (hoverPx !== null) {
        var idx = 0, best = Infinity;
        for (var i = 0; i < n; i++) {
          var d = Math.abs(g.x(xs[i]) - hoverPx);
          if (d < best) { best = d; idx = i; }
        }
        var hx = g.x(xs[idx]);
        g.ctx.strokeStyle = C.cross; g.ctx.lineWidth = 1; g.ctx.setLineDash([]);
        g.ctx.beginPath(); g.ctx.moveTo(hx, g.padT); g.ctx.lineTo(hx, g.padT + g.ph); g.ctx.stroke();
        var rows = [fmtDate(times[idx], true) + ' · ' + (isLive[idx] ? 'live' : 'hindcast')];
        if (p50[idx] != null) {
          g.ctx.fillStyle = C.cyan;
          g.ctx.beginPath(); g.ctx.arc(hx, g.y(p50[idx]), 3, 0, Math.PI * 2); g.ctx.fill();
          rows.push(['median', f1(p50[idx]) + '°F', C.cyan]);
        }
        if (p05[idx] != null && p95[idx] != null) rows.push(['90% band', f1(p05[idx]) + '–' + f1(p95[idx]) + '°', C.muted]);
        if (act[idx] != null) {
          g.ctx.fillStyle = C.white;
          if (isLive[idx]) { g.ctx.beginPath(); g.ctx.arc(hx, g.y(act[idx]), 3, 0, Math.PI * 2); g.ctx.fill(); }
          else { g.ctx.lineWidth = 1.3; g.ctx.beginPath(); g.ctx.arc(hx, g.y(act[idx]), 3, 0, Math.PI * 2); g.ctx.stroke(); }
          rows.push(['actual', f1(act[idx]) + '°F', C.ink]);
          if (p50[idx] != null) rows.push(['miss', (p50[idx] - act[idx] >= 0 ? '+' : '') + f1(p50[idx] - act[idx]) + '°', C.muted]);
        }
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

  /* ---- 03. skill by lead (two small charts) + table ---- */
  function leadCharts(byLead) {
    if (!byLead.length) return;
    var hs = byLead.map(function (d) { return d.h; });
    var x1 = Math.max.apply(null, hs);

    /* error vs persistence */
    (function () {
      var canvas = document.getElementById('tr-skill');
      if (!canvas) return;
      var mae = byLead.map(function (d) { return num(d.mae_f); });
      var maep = byLead.map(function (d) { return num(d.mae_persist_f); });
      var maxY = Math.max.apply(null, maep.concat(mae).filter(function (x) { return x != null; }));
      maxY = Math.ceil((maxY || 1) + 0.5);
      lineChart(canvas, {
        xs: hs, x0: 0, x1: x1, y0: 0, y1: maxY, yTicks: ticksFor(0, maxY, 1), yUnit: '°',
        xTicks: hs.map(function (v) { return { v: v, label: v + 'h' }; }),
        series: [
          { name: 'persistence', ys: maep, color: C.faint, width: 1.6, dash: [5, 4] },
          { name: 'model MAE', ys: mae, color: C.cyan, width: 2.2 },
        ],
        fmt: function (val) { return f2(val) + '°'; }, xLabel: function (val) { return '+' + val + 'h lead'; },
        note: 'persistence (dashed) · model (solid)',
      });
    })();

    /* observed 90% coverage by lead, with the 90% target line */
    (function () {
      var canvas = document.getElementById('tr-leadcov');
      if (!canvas) return;
      var c90 = byLead.map(function (d) { return num(d.cover90); });
      lineChart(canvas, {
        xs: hs, x0: 0, x1: x1, y0: 0, y1: 1, yTicks: [0, 0.25, 0.5, 0.75, 0.9, 1],
        xTicks: hs.map(function (v) { return { v: v, label: v + 'h' }; }),
        refLines: [{ y: 0.9, color: C.cyan }],
        series: [{ name: '90% coverage', ys: c90, color: C.cyan, width: 2.2 }],
        fmt: function (val) { return pct(val); }, xLabel: function (val) { return '+' + val + 'h lead'; },
        note: 'observed (solid) · 90% target (dashed)',
      });
    })();
  }

  function leadTable(byLead) {
    var tbl = document.getElementById('tr-table');
    if (!tbl) return;
    if (!byLead.length) { tbl.parentNode.style.display = 'none'; return; }
    var head = '<tr><th>lead</th><th>n</th><th>MAE</th><th>persistence</th><th>skill</th><th>bias</th><th>cover 90</th><th>cover 50</th></tr>';
    tbl.innerHTML = head + byLead.map(function (d) {
      var mae = num(d.mae_f), mp = num(d.mae_persist_f);
      var skill = (mae != null && mp) ? Math.round((1 - mae / mp) * 100) : null;
      var skillCls = skill == null ? '' : (skill > 2 ? ' class="win"' : (skill < -2 ? '' : ' class="tie"'));
      var skillTxt = skill == null ? '—' : (skill >= 0 ? '+' : '') + skill + '%';
      return '<tr><td>+' + d.h + 'h</td><td>' + (num(d.n) != null ? d.n : '—') + '</td><td>' + f2(mae) +
        '</td><td>' + f2(mp) + '</td><td' + skillCls + '>' + skillTxt + '</td><td>' + f2(num(d.bias_f)) +
        '</td><td>' + pct(num(d.cover90)) + '</td><td>' + pct(num(d.cover50)) + '</td></tr>';
    }).join('');
  }

  /* ---- 04. calibration bars: observed coverage vs claimed, by lead ---- */
  function calibChart(byLead, bandScale) {
    var canvas = document.getElementById('tr-calib');
    if (!canvas) return;
    if (!byLead.length) {
      register(function () {
        var g = chart(canvas, { x0: 0, x1: 1, y0: 0, y1: 1, yTicks: [], xTicks: [] });
        g.ctx.fillStyle = C.faint; g.ctx.textAlign = 'center';
        g.ctx.fillText('coverage fills in as forecasts resolve', g.padL + g.pw / 2, g.padT + g.ph / 2);
      });
      return;
    }
    var hs = byLead.map(function (d) { return d.h; });
    var c90 = byLead.map(function (d) { return num(d.cover90); });
    var c50 = byLead.map(function (d) { return num(d.cover50); });
    var hoverIdx = null;

    function draw() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (!canvas.dataset.baseh) canvas.dataset.baseh = canvas.getAttribute('height');
      var w = canvas.clientWidth, hgt = parseInt(canvas.dataset.baseh, 10);
      canvas.style.height = hgt + 'px'; canvas.width = w * dpr; canvas.height = hgt * dpr;
      var ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.font = '10px ' + MONO;
      var padL = 42, padR = 14, padT = 14, padB = 26;
      var pw = w - padL - padR, ph = hgt - padT - padB;
      var y = function (val) { return padT + ph - val * ph; };

      /* y gridlines + ticks */
      ctx.strokeStyle = C.rule; ctx.lineWidth = 1; ctx.fillStyle = C.faint;
      [0, 0.25, 0.5, 0.75, 1].forEach(function (t) {
        ctx.beginPath(); ctx.moveTo(padL, y(t)); ctx.lineTo(padL + pw, y(t)); ctx.stroke();
        ctx.textAlign = 'right'; ctx.fillText(Math.round(t * 100) + '%', padL - 5, y(t) + 3);
      });

      var groupW = pw / hs.length;
      var barW = Math.min(18, groupW * 0.28);
      hs.forEach(function (h, i) {
        var cx = padL + groupW * (i + 0.5);
        if (i === hoverIdx) { ctx.fillStyle = C.accentSoft; ctx.fillRect(padL + groupW * i, padT, groupW, ph); }
        /* 90% bar (blue) */
        if (c90[i] != null) {
          ctx.fillStyle = C.cyan;
          ctx.fillRect(cx - barW - 2, y(c90[i]), barW, y(0) - y(c90[i]));
        }
        /* 50% bar (yellow) */
        if (c50[i] != null) {
          ctx.fillStyle = C.yellow;
          ctx.fillRect(cx + 2, y(c50[i]), barW, y(0) - y(c50[i]));
        }
        ctx.fillStyle = i === hoverIdx ? C.ink : C.faint; ctx.textAlign = 'center';
        ctx.fillText('+' + h + 'h', cx, padT + ph + 16);
      });

      /* target reference lines */
      ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
      ctx.strokeStyle = C.cyan; ctx.beginPath(); ctx.moveTo(padL, y(0.9)); ctx.lineTo(padL + pw, y(0.9)); ctx.stroke();
      ctx.strokeStyle = C.yellow; ctx.beginPath(); ctx.moveTo(padL, y(0.5)); ctx.lineTo(padL + pw, y(0.5)); ctx.stroke();
      ctx.setLineDash([]);
      ctx.textAlign = 'left'; ctx.fillStyle = C.cyan; ctx.fillText('90% target', padL + 4, y(0.9) - 4);
      ctx.fillStyle = C.yellow; ctx.fillText('50% target', padL + 4, y(0.5) - 4);

      ctx.fillStyle = C.muted; ctx.textAlign = 'left';
      ctx.fillText('90% band (blue) · 50% band (yellow) · observed coverage', padL + 4, padT + 2);

      if (hoverIdx != null) {
        var rows = ['+' + hs[hoverIdx] + 'h lead'];
        if (c90[hoverIdx] != null) rows.push(['90% band', pct(c90[hoverIdx]) + ' (target 90%)', C.cyan]);
        if (c50[hoverIdx] != null) rows.push(['50% band', pct(c50[hoverIdx]) + ' (target 50%)', C.yellow]);
        tooltip({ ctx: ctx, padL: padL, padT: padT, pw: pw, ph: ph }, padL + groupW * (hoverIdx + 0.5), rows);
      }
    }
    canvas.addEventListener('mousemove', function (e) {
      var rect = canvas.getBoundingClientRect();
      var rel = (e.clientX - rect.left - 42) / (rect.width - 42 - 14);
      var i = Math.floor(rel * hs.length);
      hoverIdx = (i >= 0 && i < hs.length) ? i : null;
      window.requestAnimationFrame(draw);
    });
    canvas.addEventListener('mouseleave', function () { hoverIdx = null; window.requestAnimationFrame(draw); });
    register(draw);
  }

  /* ---- 04 note: band_scale + multi-season backtest reference ---- */
  function bandScaleNote(bandScale, bt, byLead) {
    var el = document.getElementById('tr-bandscale');
    if (!el) return;
    var parts = [];
    var bs = num(bandScale);
    if (bs != null) {
      if (bs >= 1.03) {
        parts.push('Right now the bands are running ' + bs.toFixed(2) + '× their typical width because recent forecasts have been a bit harder than usual.');
      } else if (bs <= 0.97) {
        parts.push('Right now the bands are running ' + bs.toFixed(2) + '× their typical width because recent forecasts have been calmer than usual.');
      } else {
        parts.push('Right now the bands are running at about their typical width (' + bs.toFixed(2) + '×).');
      }
    }
    if (bt) {
      var stat = num(bt.cover90_spread_static), adap = num(bt.cover90_spread_adaptive);
      var tp = num(bt.total_pairs), folds = num(bt.n_folds);
      if (stat != null && adap != null) {
        parts.push('Across ' + (folds || 'multiple') + ' replayed seasons (' +
          (tp != null ? tp.toLocaleString() : 'many') + ' forecast/outcome pairs), the spread in 90 percent coverage between seasons dropped from ' +
          (stat * 100).toFixed(1) + ' points to ' + (adap * 100).toFixed(1) + ' points after we made the bands adaptive, so the band stays honest from a placid autumn to a volatile spring.');
      } else if (tp != null) {
        parts.push('The bands are calibrated on a ' + (folds || 'multi') + '-season rolling backtest of ' + tp.toLocaleString() + ' genuinely out-of-sample forecast/outcome pairs.');
      }
    }
    el.textContent = parts.length ? parts.join(' ') : '';
    if (!parts.length) el.innerHTML = '&nbsp;';
  }

  /* generic interactive multi-series line chart (same shape as app.js) */
  function lineChart(canvas, cfg) {
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
})();
