/* Dashboard renderer: data.json (live forecast) + stats.json (validation).
   All charts are plain canvas with a shared axis helper. */
(function () {
  'use strict';

  var C = {
    ink: '#cfdce8', muted: '#7d93a8', faint: '#5d7283', rule: 'rgba(140,165,190,0.15)',
    cyan: '#39c2ff', red: '#ff4d4d', yellow: '#ffd23e', green: '#3ddc6a', white: '#ffffff',
  };
  var MONO = '"JetBrains Mono", ui-monospace, Menlo, monospace';

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

  Promise.all([
    fetch('/data.json').then(function (r) { return r.json(); }),
    fetch('/stats.json').then(function (r) { return r.json(); }),
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

    /* fan, with a hover crosshair that tracks the cursor */
    var fanCanvas = document.getElementById('fan');
    var fanHover = null;
    var X0 = -48, X1 = 168;
    function drawFan() {
      var tr = data.trajectory;
      var hist = data.history || [];
      var hs = tr.map(function (p) { return p.h; });
      var lo = Infinity, hi = -Infinity;
      tr.forEach(function (p) { lo = Math.min(lo, p.p05); hi = Math.max(hi, p.p95); });
      hist.forEach(function (p) { lo = Math.min(lo, p.f); hi = Math.max(hi, p.f); });
      lo = Math.floor(lo - 0.5); hi = Math.ceil(hi + 0.5);
      var xt = [];
      hist.concat(tr).forEach(function (p) {
        var d = new Date(p.t);
        if (d.getUTCHours() === 0) {
          xt.push({ v: p.h, label: d.toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric', timeZone: 'UTC' }) });
        }
      });
      var g = chart(fanCanvas,
        { x0: X0, x1: X1, y0: lo, y1: hi, yTicks: ticksFor(lo, hi, 1), yUnit: '°', xTicks: xt, xGrid: true, padR: 44 });

      // observed history, then the forecast fan
      band(g, hs, tr.map(function (p) { return p.p05; }), tr.map(function (p) { return p.p95; }), 'rgba(57,194,255,0.12)');
      band(g, hs, tr.map(function (p) { return p.p25; }), tr.map(function (p) { return p.p75; }), 'rgba(57,194,255,0.20)');
      line(g, hist.map(function (p) { return p.h; }), hist.map(function (p) { return p.f; }), C.white, 1.5);
      line(g, hs, tr.map(function (p) { return p.p50; }), C.cyan, 2.2);

      // now divider
      line(g, [0, 0], [lo, hi], 'rgba(207,220,232,0.35)', 1, [4, 4]);
      g.ctx.fillStyle = C.white;
      g.ctx.beginPath();
      g.ctx.arc(g.x(0), g.y(data.now.wtmp_f), 3.5, 0, Math.PI * 2);
      g.ctx.fill();
      g.ctx.textAlign = 'left';
      g.ctx.fillText('now ' + data.now.wtmp_f.toFixed(1) + '°', g.x(0) + 7, g.y(data.now.wtmp_f) - 9);
      g.ctx.fillStyle = C.faint;
      g.ctx.fillText('observed', g.x(X0) + 4, g.padT + 10);
      g.ctx.fillStyle = C.muted;
      g.ctx.fillText('forecast', g.x(8), g.padT + 10);

      // right-edge quantile labels
      var end = tr[tr.length - 1];
      [['p95', C.faint, 'P95'], ['p50', C.cyan, 'P50'], ['p05', C.faint, 'P5']].forEach(function (kq) {
        g.ctx.fillStyle = kq[1];
        g.ctx.textAlign = 'left';
        g.ctx.fillText(kq[2] + ' ' + end[kq[0]].toFixed(1) + '°', g.x(168) + 5, g.y(end[kq[0]]) + 3);
      });

      if (fanHover !== null && fanHover < 0) {
        // hovering the observed side: simple readout
        var hp = null;
        hist.forEach(function (q) { if (q.h === fanHover) hp = q; });
        if (hp) {
          var hx = g.x(hp.h);
          g.ctx.strokeStyle = 'rgba(207,220,232,0.5)';
          g.ctx.lineWidth = 1;
          g.ctx.beginPath();
          g.ctx.moveTo(hx, g.padT);
          g.ctx.lineTo(hx, g.padT + g.ph);
          g.ctx.stroke();
          g.ctx.fillStyle = C.white;
          g.ctx.beginPath();
          g.ctx.arc(hx, g.y(hp.f), 3, 0, Math.PI * 2);
          g.ctx.fill();
          g.ctx.textAlign = 'center';
          g.ctx.fillText('observed ' + hp.f.toFixed(1) + '°', hx, g.y(hp.f) - 10);
        }
      }
      if (fanHover !== null && fanHover >= 1 && fanHover <= tr.length) {
        var p = tr[fanHover - 1];
        var cx = g.x(p.h);
        g.ctx.strokeStyle = 'rgba(255, 91, 209, 0.8)';
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
        var bw = 0;
        lines.forEach(function (l) { bw = Math.max(bw, g.ctx.measureText(l).width); });
        bw += 20;
        var bh = lines.length * 15 + 12;
        var bx = cx + 12;
        if (bx + bw > g.padL + g.pw) bx = cx - bw - 12;
        var by = g.padT + 6;
        g.ctx.fillStyle = 'rgba(10, 12, 14, 0.92)';
        g.ctx.strokeStyle = 'rgba(255, 91, 209, 0.5)';
        g.ctx.beginPath();
        g.ctx.roundRect(bx, by, bw, bh, 5);
        g.ctx.fill();
        g.ctx.stroke();
        g.ctx.textAlign = 'left';
        lines.forEach(function (l, i) {
          g.ctx.fillStyle = i === 0 ? C.yellow : i === 1 ? C.white : C.muted;
          g.ctx.fillText(l, bx + 10, by + 18 + i * 15);
        });
      }
    }
    register(drawFan);
    function fanMove(e) {
      var rect = fanCanvas.getBoundingClientRect();
      var clientX = e.touches ? e.touches[0].clientX : e.clientX;
      var frac = (clientX - rect.left - 42) / (rect.width - 42 - 44);
      var h = Math.round(X0 + frac * (X1 - X0));
      h = Math.max(X0, Math.min(X1, h));
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

    /* skill curve */
    register(function () {
      var hs = stats.horizons.map(function (s) { return s.h; });
      var maxY = Math.ceil(Math.max.apply(null, stats.horizons.map(function (s) { return s.mae_persistence; })) + 0.5);
      var g = chart(document.getElementById('skill'),
        { x0: 0, x1: 168, y0: 0, y1: maxY, yTicks: ticksFor(0, maxY, 1), yUnit: '°',
          xTicks: [24, 48, 72, 96, 120, 144, 168].map(function (v) { return { v: v, label: v + 'h' }; }) });
      line(g, hs, stats.horizons.map(function (s) { return s.mae_persistence; }), C.faint, 1.6, [5, 4]);
      line(g, hs, stats.horizons.map(function (s) { return s.mae; }), C.cyan, 2.2);
      line(g, hs, stats.horizons.map(function (s) { return s.p90_abs_err; }), C.cyan, 1, [2, 3]);
      g.ctx.fillStyle = C.muted;
      g.ctx.textAlign = 'left';
      g.ctx.fillText('persistence (dashed) · model MAE (solid) · model P90 |err| (dotted)', g.padL + 4, g.padT + 2);
    });

    /* coverage */
    register(function () {
      var hs = stats.horizons.map(function (s) { return s.h; });
      var g = chart(document.getElementById('coverage'),
        { x0: 0, x1: 168, y0: 0, y1: 1, yTicks: [0, 0.25, 0.5, 0.75, 0.9, 1],
          xTicks: [24, 48, 72, 96, 120, 144, 168].map(function (v) { return { v: v, label: v + 'h' }; }) });
      line(g, [0, 168], [0.9, 0.9], C.cyan, 0.8, [4, 4]);
      line(g, [0, 168], [0.5, 0.5], C.yellow, 0.8, [4, 4]);
      line(g, hs, stats.horizons.map(function (s) { return s.cover90; }), C.cyan, 2);
      line(g, hs, stats.horizons.map(function (s) { return s.cover50; }), C.yellow, 2);
    });

    /* hindcast */
    register(function () {
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
      var g = chart(document.getElementById('hindcast'),
        { x0: 0, x1: n - 1, y0: lo, y1: hi, yTicks: ticksFor(lo, hi, 2), yUnit: '°', xTicks: xt, xGrid: true });
      band(g, xs, hc.p05, hc.p95, 'rgba(57,194,255,0.12)');
      line(g, xs, hc.p50, C.cyan, 1.4);
      line(g, xs, hc.actual, C.white, 1.4);
      g.ctx.fillStyle = C.muted;
      g.ctx.textAlign = 'left';
      g.ctx.fillText('actual (white) · +24h median (cyan) · 90% band (shaded)', g.padL + 4, g.padT + 2);
    });

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
        g.ctx.fillStyle = r.edges[i] >= -0.25 && r.edges[i + 1] <= 0.25 ? C.cyan : 'rgba(57,194,255,0.45)';
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
      g.ctx.fillStyle = 'rgba(57,194,255,0.5)';
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

    /* backtest card */
    if (stats.backtest) {
      var bt = stats.backtest;
      var i24 = bt.horizons.indexOf(24);
      var iEnd = bt.horizons.length - 1;
      document.getElementById('backtest-card').hidden = false;
      document.getElementById('backtest-cap').textContent =
        bt.total_pairs.toLocaleString() + ' forecast/outcome pairs across ' + bt.folds.length +
        ' season-end windows (' + bt.folds.map(function (f) { return f.name; }).join(', ') +
        '), each fold trained only on data ending 8 days before its window. Five-season mean MAE: ' +
        bt.mean_mae[i24].toFixed(2) + '°F at +24h and ' + bt.mean_mae[iEnd].toFixed(2) +
        '°F at +168h, vs persistence at ' + bt.mean_mae_persist[i24].toFixed(2) + ' and ' +
        bt.mean_mae_persist[iEnd].toFixed(2) + '. Mean 90% band coverage ' +
        Math.round(bt.mean_cover90.reduce(function (a, b) { return a + b; }, 0) / bt.mean_cover90.length * 100) + '%.';
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
