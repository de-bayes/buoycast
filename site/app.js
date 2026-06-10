/* Dashboard renderer: loads data.json and draws the 7-day fan chart, the
   24-hour strip, and the skill bars on plain canvas. */
(function () {
  'use strict';

  var C = {
    ink: '#cfdce8', muted: '#7d93a8', faint: '#5d7283', rule: 'rgba(140,165,190,0.16)',
    cyan: '#39c2ff', red: '#ff4d4d', yellow: '#ffd23e', green: '#3ddc6a',
  };
  var MONO = '"JetBrains Mono", ui-monospace, Menlo, monospace';

  function setup(canvas) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = canvas.clientWidth, h = parseInt(canvas.getAttribute('height'), 10);
    canvas.style.height = h + 'px';
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.font = '10px ' + MONO;
    return { ctx: ctx, w: w, h: h };
  }

  function frame(ctx, padL, padT, w, h, yMin, yMax, step) {
    ctx.strokeStyle = C.rule;
    ctx.fillStyle = C.faint;
    ctx.lineWidth = 1;
    for (var t = Math.ceil(yMin / step) * step; t <= yMax; t += step) {
      var y = padT + h - ((t - yMin) / (yMax - yMin)) * h;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + w, y);
      ctx.stroke();
      ctx.textAlign = 'right';
      ctx.fillText(t + '°', padL - 6, y + 3);
    }
  }

  function fanChart(canvas, data) {
    var s = setup(canvas), ctx = s.ctx;
    var padL = 40, padR = 16, padT = 12, padB = 26;
    var w = s.w - padL - padR, h = s.h - padT - padB;

    var pts = [{ x: 0, v: data.now.wtmp_f, mae: 0, label: 'now' }];
    data.daily.forEach(function (d) {
      pts.push({ x: d.k, v: d.wtmp_f, mae: d.mae_f, label: d.label });
    });
    var lo = Infinity, hi = -Infinity;
    pts.forEach(function (p) { lo = Math.min(lo, p.v - p.mae); hi = Math.max(hi, p.v + p.mae); });
    lo = Math.floor(lo - 1); hi = Math.ceil(hi + 1);

    var X = function (k) { return padL + (k / 7) * w; };
    var Y = function (v) { return padT + h - ((v - lo) / (hi - lo)) * h; };

    frame(ctx, padL, padT, w, h, lo, hi, 2);

    ctx.fillStyle = 'rgba(57, 194, 255, 0.16)';
    ctx.beginPath();
    pts.forEach(function (p, i) { i ? ctx.lineTo(X(p.x), Y(p.v + p.mae)) : ctx.moveTo(X(p.x), Y(p.v + p.mae)); });
    for (var i = pts.length - 1; i >= 0; i--) ctx.lineTo(X(pts[i].x), Y(pts[i].v - pts[i].mae));
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = C.cyan;
    ctx.lineWidth = 2.2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    pts.forEach(function (p, i) { i ? ctx.lineTo(X(p.x), Y(p.v)) : ctx.moveTo(X(p.x), Y(p.v)); });
    ctx.stroke();

    pts.forEach(function (p) {
      ctx.fillStyle = p.x === 0 ? '#fff' : C.cyan;
      ctx.beginPath();
      ctx.arc(X(p.x), Y(p.v), 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.textAlign = 'center';
      ctx.fillStyle = C.ink;
      ctx.fillText(p.v.toFixed(0) + '°', X(p.x), Y(p.v) - 9);
      ctx.fillStyle = C.faint;
      ctx.fillText(p.label, X(p.x), padT + h + 16);
    });
  }

  function hourlyChart(canvas, data) {
    var s = setup(canvas), ctx = s.ctx;
    var padL = 40, padR = 16, padT = 14, padB = 24;
    var w = s.w - padL - padR, h = s.h - padT - padB;
    var pts = [{ h: 0, v: data.now.wtmp_f, mae: 0, label: 'now' }];
    data.hourly.forEach(function (d) { pts.push({ h: d.h, v: d.wtmp_f, mae: d.mae_f, label: '+' + d.h + 'h' }); });
    var lo = Infinity, hi = -Infinity;
    pts.forEach(function (p) { lo = Math.min(lo, p.v - p.mae); hi = Math.max(hi, p.v + p.mae); });
    lo = Math.floor(lo - 0.5); hi = Math.ceil(hi + 0.5);
    var X = function (k) { return padL + (k / 24) * w; };
    var Y = function (v) { return padT + h - ((v - lo) / (hi - lo)) * h; };
    frame(ctx, padL, padT, w, h, lo, hi, 1);
    ctx.fillStyle = 'rgba(57, 194, 255, 0.16)';
    ctx.beginPath();
    pts.forEach(function (p, i) { i ? ctx.lineTo(X(p.h), Y(p.v + p.mae)) : ctx.moveTo(X(p.h), Y(p.v + p.mae)); });
    for (var i = pts.length - 1; i >= 0; i--) ctx.lineTo(X(pts[i].h), Y(pts[i].v - pts[i].mae));
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = C.cyan;
    ctx.lineWidth = 2;
    ctx.beginPath();
    pts.forEach(function (p, i) { i ? ctx.lineTo(X(p.h), Y(p.v)) : ctx.moveTo(X(p.h), Y(p.v)); });
    ctx.stroke();
    pts.forEach(function (p) {
      ctx.fillStyle = p.h === 0 ? '#fff' : C.cyan;
      ctx.beginPath();
      ctx.arc(X(p.h), Y(p.v), 2.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = C.ink;
      ctx.textAlign = 'center';
      ctx.fillText(p.v.toFixed(1) + '°', X(p.h), Y(p.v) - 8);
      ctx.fillStyle = C.faint;
      ctx.fillText(p.label, X(p.h), padT + h + 15);
    });
  }

  function skillChart(canvas, groups, series) {
    var s = setup(canvas), ctx = s.ctx;
    var padL = 34, padR = 8, padT = 12, padB = 26;
    var w = s.w - padL - padR, h = s.h - padT - padB;
    var maxV = 0;
    groups.forEach(function (g) { series.forEach(function (sr) { if (g[sr.key] != null) maxV = Math.max(maxV, g[sr.key]); }); });
    maxV = Math.ceil(maxV * 1.15 * 2) / 2;
    frame(ctx, padL, padT, w, h, 0, maxV, maxV > 2 ? 1 : 0.5);
    var gw = w / groups.length;
    var bw = Math.min(16, (gw - 14) / series.length);
    groups.forEach(function (g, gi) {
      var cx = padL + gi * gw + gw / 2;
      series.forEach(function (sr, si) {
        var v = g[sr.key];
        if (v == null) return;
        var x = cx + (si - (series.length - 1) / 2) * (bw + 3) - bw / 2;
        var bh = (v / maxV) * h;
        ctx.fillStyle = sr.color;
        ctx.fillRect(x, padT + h - bh, bw, bh);
      });
      ctx.fillStyle = C.faint;
      ctx.textAlign = 'center';
      ctx.fillText(g.label, cx, padT + h + 16);
    });
    var lx = padL + 4;
    series.forEach(function (sr) {
      ctx.fillStyle = sr.color;
      ctx.fillRect(lx, padT - 6, 8, 8);
      ctx.fillStyle = C.muted;
      ctx.textAlign = 'left';
      ctx.fillText(sr.name, lx + 12, padT + 2);
      lx += 12 + ctx.measureText(sr.name).width + 16;
    });
  }

  fetch('/data.json').then(function (r) { return r.json(); }).then(function (data) {
    var gen = new Date(data.generated_utc);
    document.getElementById('stamp').textContent =
      'UPDATED ' + gen.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).toUpperCase();

    document.getElementById('now-wtmp').textContent = data.now.wtmp_f.toFixed(1) + '°F';
    var grid = document.getElementById('now-grid');
    [['AIR', data.now.atmp_f.toFixed(1) + '°F'], ['WAVES', data.now.wvht_ft + ' ft'],
     ['WIND', data.now.wspd_kt + ' kt'], ['GUSTS', data.now.gst_kt + ' kt']].forEach(function (kv) {
      var d = document.createElement('div');
      d.innerHTML = '<span>' + kv[0] + '</span><b>' + kv[1] + '</b>';
      grid.appendChild(d);
    });

    fanChart(document.getElementById('fan'), data);
    hourlyChart(document.getElementById('hourly'), data);

    var hg = Object.keys(data.metrics.hourly).map(function (k) {
      var m = data.metrics.hourly[k];
      return { label: k, persist: m.persistence.test_mae_f, lags: m.lasso_lags_only.test_mae_f, model: m[m.best].test_mae_f };
    });
    skillChart(document.getElementById('skill-hourly'), hg, [
      { key: 'persist', name: 'persistence', color: '#5d7283' },
      { key: 'lags', name: 'lags only', color: '#7d93a8' },
      { key: 'model', name: 'full model', color: C.cyan },
    ]);

    var dg = Object.keys(data.metrics.daily).map(function (k) {
      var m = data.metrics.daily[k];
      return { label: k, persist: m.persistence.test_mae_f, model: m[m.best].test_mae_f };
    });
    skillChart(document.getElementById('skill-daily'), dg, [
      { key: 'persist', name: 'persistence', color: '#5d7283' },
      { key: 'model', name: 'full model', color: C.cyan },
    ]);

    window.addEventListener('resize', function () {
      fanChart(document.getElementById('fan'), data);
      hourlyChart(document.getElementById('hourly'), data);
      skillChart(document.getElementById('skill-hourly'), hg, [
        { key: 'persist', name: 'persistence', color: '#5d7283' },
        { key: 'lags', name: 'lags only', color: '#7d93a8' },
        { key: 'model', name: 'full model', color: C.cyan },
      ]);
      skillChart(document.getElementById('skill-daily'), dg, [
        { key: 'persist', name: 'persistence', color: '#5d7283' },
        { key: 'model', name: 'full model', color: C.cyan },
      ]);
    });
  }).catch(function () {
    document.getElementById('stamp').textContent = 'DATA UNAVAILABLE, RUN publish.py';
  });
})();
