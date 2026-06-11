/* Animated explainers for /ml. Every figure is plain canvas, light theme,
   started when it scrolls into view via IntersectionObserver. The methods are
   illustrated, not the production model. Vanilla JS, no dependencies.

   Animation contract: PLAY ONCE, THEN FREEZE.
   - Each figure starts the moment it scrolls into view (threshold 0.35), plays
     its full sequence exactly once over a fixed DURATION, then renders its
     final, most informative composed frame and STOPS its timer completely. No
     fades-to-restart, no breathing, no ping-pong, zero CPU once frozen.
   - Every frame function reads a monotonic time clamped to [0, DURATION]. At
     t === DURATION it must draw the intended final state, so the frozen frame
     and the last animated frame are identical.
   - A caption replay button restarts a figure's timeline from zero at any time.
   - A window resize re-renders the frozen final frame once (the self-healing
     sizing handles the bitmap; we re-run the frame at the stored final time).

   Robustness note (a real bug): the bitmap is re-measured and re-sized on EVERY
   frame, never cached across frames. IBM Plex loads async and reflows the
   layout, so a once-measured canvas would stretch. Self-healing each frame
   fixes the giant/blurry/blank classes of bug. */
(function () {
  'use strict';

  var C = {
    ink: '#16181d', muted: '#5b6470', faint: '#9aa1ab',
    grid: 'rgba(20,24,30,0.07)', accent: '#1257a0',
    band: 'rgba(18,87,160,0.12)', band2: 'rgba(18,87,160,0.22)',
    member: 'rgba(120,130,142,0.7)', amber: '#b45309', green: '#2f7d5b',
    dot: 'rgba(20,24,30,0.45)', truth: 'rgba(20,24,30,0.24)'
  };
  var MONO = '11px "IBM Plex Mono", ui-monospace, Menlo, monospace';

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function ease(p) { p = clamp(p, 0, 1); return 1 - Math.pow(1 - p, 3); }       // easeOutCubic, for draws
  function easeIO(p) { p = clamp(p, 0, 1); return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; } // for movement

  /* Per-frame self-healing setup. Reads clientWidth every call; resizes the
     bitmap only when the CSS width changed (or first frame). Caps dpr at 2. */
  function makeFig(c) {
    var lastW = -1, ctx = c.getContext('2d'), attrH = parseInt(c.getAttribute('height'), 10) || 240;
    return function sync() {
      var cssW = c.clientWidth || 600;
      if (cssW !== lastW) {
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        c.style.height = attrH + 'px';
        c.width = Math.round(cssW * dpr);
        c.height = Math.round(attrH * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        lastW = cssW;
      }
      ctx.clearRect(0, 0, cssW, attrH);
      ctx.font = MONO; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
      ctx.textBaseline = 'alphabetic';
      return { ctx: ctx, w: cssW, h: attrH };
    };
  }

  /* now(): wall-clock seconds. Driven via setTimeout (not rAF) so the loop
     advances both at 60fps in real browsers AND under headless virtual time
     (where requestAnimationFrame is throttled to a single frame but timers and
     performance.now() track the virtual-time budget). */
  function now() { return (window.performance && performance.now ? performance.now() : Date.now()); }

  /* Play-once-then-freeze driver bound to visibility.
       frame(s, t)   -- t is monotonic seconds, clamped to [0, dur].
       dur           -- total animation length; at t === dur the figure is at
                        its final composed state.
     Lifecycle: the figure starts when it first scrolls into view (threshold
     0.35). It advances the timer until t reaches dur, renders that final frame
     once, then STOPS the timer (no further CPU). A window resize re-renders the
     frozen final frame once. replay() restarts the timeline from zero, even
     mid-play, and resumes the timer. */
  var REGISTRY = {};                                    // id -> driver, for generic replay wiring
  function loop(id, frame, dur) {
    var c = document.getElementById(id);
    if (!c) return null;
    var sync = makeFig(c), timer = null, t0 = 0, vis = false, done = false;
    function render(t) { frame(sync(), t); }
    function step() {
      if (!vis) { timer = null; return; }               // pause off-screen; resumes where it left off
      var t = (now() - t0) / 1000;
      if (t >= dur) { render(dur); done = true; timer = null; return; }   // final frame, then stop
      render(t);
      timer = window.setTimeout(step, 16);
    }
    function start() { if (timer == null && !done) { step(); } }
    function replay() { t0 = now(); done = false; if (timer == null) { timer = window.setTimeout(step, 0); } }
    new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        vis = e.isIntersecting;
        if (vis && !done && timer == null) { if (!t0) t0 = now(); start(); }
      });
    }, { threshold: 0.35 }).observe(c);
    // re-render the frozen final frame on resize (self-healing sizing redraws the bitmap)
    window.addEventListener('resize', function () { if (done) render(dur); });
    var driver = { replay: replay };
    REGISTRY[id] = driver;
    return driver;
  }

  /* Wire a caption replay button (id) to its figure (figId). */
  function wireReplay(figId, btnId) {
    var btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', function () { var d = REGISTRY[figId]; if (d) d.replay(); });
  }

  /* ---- drawing helpers ---- */
  function mapper(s, pad, ylo, yhi) {
    var iw = s.w - pad.l - pad.r, ih = s.h - pad.t - pad.b;
    return {
      X: function (v) { return pad.l + v * iw; },
      Y: function (v) { return pad.t + (1 - (v - ylo) / (yhi - ylo)) * ih; }
    };
  }
  function poly(ctx, pts, color, w, dash) {
    if (pts.length < 2) return;
    ctx.strokeStyle = color; ctx.lineWidth = w; ctx.setLineDash(dash || []);
    ctx.beginPath();
    for (var i = 0; i < pts.length; i++) i ? ctx.lineTo(pts[i][0], pts[i][1]) : ctx.moveTo(pts[i][0], pts[i][1]);
    ctx.stroke(); ctx.setLineDash([]);
  }
  function fillBand(ctx, top, bot, color) {
    if (top.length < 2) return;
    ctx.fillStyle = color; ctx.beginPath();
    for (var i = 0; i < top.length; i++) i ? ctx.lineTo(top[i][0], top[i][1]) : ctx.moveTo(top[i][0], top[i][1]);
    for (i = bot.length - 1; i >= 0; i--) ctx.lineTo(bot[i][0], bot[i][1]);
    ctx.closePath(); ctx.fill();
  }
  function dot(ctx, x, y, r, color) { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill(); }
  // Faint horizontal gridlines with plausible y labels on the left (padL ~34).
  function gridY(s, m, pad, rows) {
    var ctx = s.ctx;
    ctx.lineWidth = 1; ctx.strokeStyle = C.grid; ctx.fillStyle = C.faint;
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    rows.forEach(function (r) {
      var y = m.Y(r.v);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(s.w - pad.r, y); ctx.stroke();
      ctx.fillText(r.t, pad.l - 6, y);
    });
    ctx.textBaseline = 'alphabetic';
  }

  /* =====================================================================
     01  the forecast fan, drawing out from now
     ===================================================================== */
  var FAN_DUR = 2.8;
  loop('a-fan', function (s, t) {
    var pad = { l: 34, r: 58, t: 16, b: 26 };
    var m = mapper(s, pad, 0.10, 0.95), ctx = s.ctx;
    var p = ease(clamp(t / FAN_DUR, 0, 1));             // draw-out 0..1, easeOut

    gridY(s, m, pad, [{ v: 0.80, t: '66°' }, { v: 0.58, t: '64°' }, { v: 0.36, t: '62°' }]);

    // faint day ticks +1d..+7d along the x axis
    ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
    ctx.fillStyle = C.faint; ctx.font = MONO; ctx.textAlign = 'center';
    for (var d = 1; d <= 7; d++) {
      var dx = m.X(d / 7);
      ctx.beginPath(); ctx.moveTo(dx, s.h - pad.b); ctx.lineTo(dx, s.h - pad.b + 3); ctx.stroke();
    }
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';

    var med = function (x) { return 0.62 - 0.10 * x + 0.035 * Math.sin(x * 4.6 + 0.6); };
    // band half-width: ~25% of plot height at the right edge (x=1)
    var hw = function (x) { return 0.02 + 0.23 * Math.pow(x, 1.1); };
    var N = 80, up = [], lo = [], mid = [];
    for (var i = 0; i <= N; i++) {
      var x = (i / N) * p;
      up.push([m.X(x), m.Y(med(x) + hw(x))]);
      lo.push([m.X(x), m.Y(med(x) - hw(x))]);
      mid.push([m.X(x), m.Y(med(x))]);
    }
    fillBand(ctx, up, lo, C.band);
    poly(ctx, mid, C.accent, 2.2);

    // 'now' dot at left
    dot(ctx, m.X(0), m.Y(med(0)), 3.5, C.ink);
    ctx.fillStyle = C.muted; ctx.textAlign = 'left';
    ctx.fillText('now', m.X(0) + 7, m.Y(med(0)) - 9);

    // right-edge labels fade in once the line is fully drawn
    if (p > 0.90) {
      var la = ease((p - 0.90) / 0.10);
      ctx.globalAlpha = la;
      ctx.fillStyle = C.faint; ctx.textAlign = 'left';
      var xr = s.w - pad.r + 5;
      ctx.fillText('P95', xr, m.Y(med(1) + hw(1)) + 3);
      ctx.fillStyle = C.accent; ctx.fillText('P50', xr, m.Y(med(1)) + 3);
      ctx.fillStyle = C.faint; ctx.fillText('P5', xr, m.Y(med(1) - hw(1)) + 3);
      ctx.globalAlpha = 1;
    }

    // x labels inside the padding
    ctx.fillStyle = C.faint; ctx.textAlign = 'left';
    ctx.fillText('+0h', pad.l, s.h - 9);
    ctx.textAlign = 'right'; ctx.fillText('+7d', s.w - pad.r, s.h - 9);
  }, FAN_DUR);

  /* =====================================================================
     02  counters: count up once when scrolled into view
     ===================================================================== */
  document.querySelectorAll('.ml-counters').forEach(function (block) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        io.disconnect();
        block.querySelectorAll('.count').forEach(function (el) {
          var to = +el.getAttribute('data-to') || 0, t0 = now();
          function fmt(v) { return to >= 1000 ? v.toLocaleString('en-US') : String(v); }
          function tick() {
            var dt = now() - t0;
            if (dt < 1300) { el.textContent = fmt(Math.round(to * ease(dt / 1300))); window.setTimeout(tick, 16); }
            else el.textContent = fmt(to);
          }
          tick();
        });
      });
    }, { threshold: 0.4 });
    io.observe(block);
  });

  /* =====================================================================
     03  gradient boosting: real depth-1 stumps fitting residuals.
     Precompute a fixed seeded dataset + cumulative predictions per stage.
     ===================================================================== */
  var BOOST = (function build() {
    var N = 70, seed = 7;
    function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }
    var xs = [], y = [], truth = [];
    for (var i = 0; i < N; i++) {
      var x = i / (N - 1); xs.push(x);
      var tv = 0.50 + 0.28 * Math.sin(x * 5.4) + 0.09 * Math.sin(x * 11 + 1);
      truth.push(tv); y.push(tv + (rnd() - 0.5) * 0.14);
    }
    var mean = y.reduce(function (a, b) { return a + b; }, 0) / N;
    var pred = []; for (i = 0; i < N; i++) pred.push(mean);
    var stages = [pred.slice()], lr = 0.35, TH = 26, TREES = 30;
    for (var it = 0; it < TREES; it++) {
      var resid = []; for (i = 0; i < N; i++) resid.push(y[i] - pred[i]);
      var best = { sse: Infinity };
      for (var th = 1; th < TH; th++) {
        var thr = th / TH, lS = 0, lN = 0, rS = 0, rN = 0;
        for (i = 0; i < N; i++) { if (xs[i] < thr) { lS += resid[i]; lN++; } else { rS += resid[i]; rN++; } }
        if (!lN || !rN) continue;
        var lM = lS / lN, rM = rS / rN, sse = 0;
        for (i = 0; i < N; i++) { var d = resid[i] - (xs[i] < thr ? lM : rM); sse += d * d; }
        if (sse < best.sse) best = { sse: sse, thr: thr, lM: lM, rM: rM };
      }
      for (i = 0; i < N; i++) pred[i] += lr * (xs[i] < best.thr ? best.lM : best.rM);
      stages.push(pred.slice());
    }
    var rmse = stages.map(function (st) {
      var se = 0; for (var j = 0; j < N; j++) { var d = st[j] - truth[j]; se += d * d; } return Math.sqrt(se / N);
    });
    return { xs: xs, y: y, truth: truth, stages: stages, rmse: rmse, N: N };
  })();

  (function boost() {
    var label = document.getElementById('boost-label');
    var pad = { l: 34, r: 18, t: 16, b: 24 };
    var STEP = 0.40;                                    // seconds per tree (smooth stage tween)
    var last = BOOST.stages.length - 1;
    var growSecs = last * STEP;
    loop('a-boost', function (s, t) {
      var ctx = s.ctx;
      var m = mapper(s, pad, 0.05, 1.0);
      var phase = clamp(t / growSecs, 0, 1);            // 0..1 over the grow

      gridY(s, m, pad, [{ v: 0.82, t: '66°' }, { v: 0.5, t: '63°' }, { v: 0.18, t: '60°' }]);

      // truth curve (dashed) + data dots
      var tp = BOOST.xs.map(function (x, i) { return [m.X(x), m.Y(BOOST.truth[i])]; });
      poly(ctx, tp, C.truth, 1.5, [4, 4]);
      BOOST.xs.forEach(function (x, i) { dot(ctx, m.X(x), m.Y(BOOST.y[i]), 2, C.dot); });

      // tween between consecutive stages so the staircase morphs smoothly
      var prog = phase * last;                          // 0..last
      var i0 = Math.min(Math.floor(prog), last), i1 = Math.min(i0 + 1, last);
      var f = ease(prog - i0);
      var a = BOOST.stages[i0], b = BOOST.stages[i1], pr = [];
      for (var k = 0; k < BOOST.N; k++) pr.push(a[k] + (b[k] - a[k]) * f);

      // staircase (sum of stumps is piecewise constant)
      ctx.strokeStyle = C.accent; ctx.lineWidth = 2.2; ctx.beginPath();
      ctx.moveTo(m.X(BOOST.xs[0]), m.Y(pr[0]));
      for (k = 1; k < BOOST.N; k++) {
        ctx.lineTo(m.X(BOOST.xs[k]), m.Y(pr[k - 1]));
        ctx.lineTo(m.X(BOOST.xs[k]), m.Y(pr[k]));
      }
      ctx.stroke();

      if (label) {
        var trees = Math.round(i0 + f);
        var rmse = BOOST.rmse[i0] + (BOOST.rmse[i1] - BOOST.rmse[i0]) * f;
        label.textContent = 'trees: ' + trees + ' · error: ' + rmse.toFixed(3);
      }
    }, growSecs);

    wireReplay('a-boost', 'boost-replay');
  })();

  /* =====================================================================
     06b  the bake-off: four learners fit ONE seeded dataset, real learned
     weights from blend.json (ridge 0, bayes 0, forest 0.45, boosting 0.55),
     then the composite 0.45*forest + 0.55*boosting draws on top. All fits
     are computed from the data, not hand-drawn, so the comparison is honest.
     ===================================================================== */
  var BAKE = (function build() {
    var N = 40, seed = 23;
    function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }
    var xs = [], y = [], truth = [];
    for (var i = 0; i < N; i++) {
      var x = i / (N - 1); xs.push(x);
      var tv = 0.48 + 0.22 * Math.sin(x * 4.2 + 0.4) + 0.07 * Math.sin(x * 9 + 1.1);
      truth.push(tv); y.push(tv + (rnd() - 0.5) * 0.13);
    }
    var GRID = 90, gx = [];
    for (i = 0; i < GRID; i++) gx.push(i / (GRID - 1));

    // ridge: ordinary least-squares straight line (ridge with negligible penalty
    // is visually a line); compute slope/intercept honestly from the dots.
    var mx = 0, my = 0;
    for (i = 0; i < N; i++) { mx += xs[i]; my += y[i]; }
    mx /= N; my /= N;
    var sxx = 0, sxy = 0;
    for (i = 0; i < N; i++) { sxx += (xs[i] - mx) * (xs[i] - mx); sxy += (xs[i] - mx) * (y[i] - my); }
    var slope = sxy / sxx, intc = my - slope * mx;
    var line = function (x) { return intc + slope * x; };
    var ridge = gx.map(line);

    // residual std around the line -> haze half-width for the bayesian band
    var rs = 0; for (i = 0; i < N; i++) { var d = y[i] - line(xs[i]); rs += d * d; }
    var resStd = Math.sqrt(rs / N);

    // forest: average of coarse bins (piecewise-constant), lightly smoothed.
    function binAvg(nbin) {
      var sum = [], cnt = [];
      for (var b = 0; b < nbin; b++) { sum.push(0); cnt.push(0); }
      for (var j = 0; j < N; j++) { var bi = Math.min(nbin - 1, Math.floor(xs[j] * nbin)); sum[bi] += y[j]; cnt[bi]++; }
      var fill = my;
      var v = [];
      for (b = 0; b < nbin; b++) { if (cnt[b]) { fill = sum[b] / cnt[b]; } v.push(fill); }
      return function (x) { var bi = Math.min(nbin - 1, Math.floor(x * nbin)); return v[bi]; };
    }
    var coarse = binAvg(8);
    // light 3-tap smoothing of the coarse step so it reads as a forest, not one tree
    var forestRaw = gx.map(coarse), forest = [];
    for (i = 0; i < GRID; i++) {
      var a = forestRaw[Math.max(0, i - 1)], c = forestRaw[i], e = forestRaw[Math.min(GRID - 1, i + 1)];
      forest.push((a + 2 * c + e) / 4);
    }

    // boosting: a finer piecewise fit (16 bins) that tracks the trend closely.
    var fine = binAvg(16);
    var boost = gx.map(fine);

    // composite: the real learned mix, forest 45% / boosting 55%.
    var composite = [];
    for (i = 0; i < GRID; i++) composite.push(0.45 * forest[i] + 0.55 * boost[i]);

    return {
      xs: xs, y: y, truth: truth, gx: gx, GRID: GRID,
      ridge: ridge, forest: forest, boost: boost, composite: composite,
      resStd: resStd, line: line
    };
  })();

  var BAKE_DUR = 14.0;
  loop('a-bakeoff', function (s, t) {
    var ctx = s.ctx;
    var pad = { l: 34, r: 64, t: 18, b: 26 };
    var m = mapper(s, pad, 0.05, 0.95);
    // one pass: members(0..8s) -> weights(8..11s) -> composite(11..14s), then freeze
    var p = clamp(t, 0, BAKE_DUR);                      // seconds into the draw, 0..14

    gridY(s, m, pad, [{ v: 0.80, t: '66°' }, { v: 0.5, t: '64°' }, { v: 0.20, t: '62°' }]);

    // the fixed data dots, always present
    BAKE.xs.forEach(function (x, i) { dot(ctx, m.X(x), m.Y(BAKE.y[i]), 2, C.dot); });

    var GR = BAKE.GRID;
    // helper: build a polyline over the first `frac` of the grid (left->right draw-on)
    function curve(arr, frac) {
      var lim = Math.max(1, Math.floor(frac * (GR - 1)));
      var pts = [];
      for (var i = 0; i <= lim; i++) pts.push([m.X(BAKE.gx[i]), m.Y(arr[i])]);
      return pts;
    }

    // tone palette (members stay, dropping to low alpha once superseded)
    var GRAY1 = 'rgba(120,130,142,0.85)';   // ridge ink
    var GRAY2 = 'rgba(96,104,116,0.85)';    // forest, second gray tone
    var BMUTED = 'rgba(40,86,140,0.78)';    // boosting, accent-adjacent but muted

    // phase 1 windows (seconds): each learner draws over ~1.7s then a label appears
    // ridge 0.2..1.9, bayes 2.2..3.9, forest 4.2..5.9, boosting 6.2..7.9
    var pComposite = clamp((p - 11.0) / 2.6, 0, 1);     // 0..1 over phase 3
    // member master alpha drops as the composite takes over
    var memberFade = 1 - 0.74 * ease(pComposite);

    // ---- active-learner emphasis (phase 1) ----
    // While its own fit is being drawn (and held until the next one starts), a
    // learner is THE active learner: full opacity, heavier stroke, ink label.
    // Once superseded it drops to ~0.35 alpha with a faint label. When phase 1
    // ends (p >= P1_END) the spotlight dissolves and all four rest at memberFade.
    var STARTS = [0.2, 2.2, 4.2, 6.2], P1_END = 8.0;
    var spot = 1 - ease(clamp((p - P1_END) / 0.5, 0, 1));   // 1 in phase 1, ->0 after
    // index of the learner currently being shown (the last one whose window opened)
    var activeIdx = -1;
    for (var ai = 0; ai < 4; ai++) if (p >= STARTS[ai]) activeIdx = ai;
    // per-learner display alpha (relative, before memberFade) and width boost
    function emphA(idx) {
      var base = (idx === activeIdx) ? 1 : 0.35;        // active full, finished dim
      return base + (1 - base) * (1 - spot);            // dimmed ones rise back at phase-1 end
    }
    function emphW(idx, baseW) { return baseW + 0.6 * spot * (idx === activeIdx ? 1 : 0); }

    // ---- ridge (straight line) ----
    var aRidge = clamp((p - 0.2) / 1.7, 0, 1);
    if (aRidge > 0) {
      ctx.globalAlpha = memberFade * emphA(0);
      poly(ctx, curve(BAKE.ridge, aRidge), GRAY1, emphW(0, 1.6));
    }

    // ---- bayesian ridge: same line + a faint uncertainty haze ----
    var aBayes = clamp((p - 2.2) / 1.7, 0, 1);
    if (aBayes > 0) {
      var hw = 1.25 * BAKE.resStd;                      // haze half-width (< plot half-height)
      var lim = Math.max(1, Math.floor(aBayes * (GR - 1)));
      var up = [], lo = [];
      for (var i = 0; i <= lim; i++) {
        up.push([m.X(BAKE.gx[i]), m.Y(BAKE.ridge[i] + hw)]);
        lo.push([m.X(BAKE.gx[i]), m.Y(BAKE.ridge[i] - hw)]);
      }
      ctx.globalAlpha = memberFade * emphA(1);
      fillBand(ctx, up, lo, 'rgba(120,130,142,0.13)');
      ctx.globalAlpha = memberFade * emphA(1);
      poly(ctx, curve(BAKE.ridge, aBayes), GRAY1, emphW(1, 1.6));
    }

    // ---- random forest (smoothed piecewise constant) ----
    var aForest = clamp((p - 4.2) / 1.7, 0, 1);
    if (aForest > 0) {
      ctx.globalAlpha = memberFade * emphA(2);
      poly(ctx, curve(BAKE.forest, aForest), GRAY2, emphW(2, 1.7));
    }

    // ---- boosting (finer staircase) ----
    var aBoost = clamp((p - 6.2) / 1.7, 0, 1);
    if (aBoost > 0) {
      ctx.globalAlpha = memberFade * emphA(3);
      poly(ctx, curve(BAKE.boost, aBoost), BMUTED, emphW(3, 1.8));
    }

    // ---- member labels (right edge), each appearing as its fit is drawn ----
    // The fits converge at the right edge, so anchor labels to fixed, well-spaced
    // slots (top..bottom) rather than to the colliding curve endpoints. The
    // active learner's label is rendered in ink at full strength; superseded
    // ones drop to a faint resting label. The spotlight dissolves after phase 1.
    ctx.textAlign = 'left'; ctx.font = MONO;
    var xr = s.w - pad.r + 5, lastIdx = GR - 1;
    var slotY = [pad.t + 16, pad.t + 32, s.h - pad.b - 30, s.h - pad.b - 14];
    function memLabel(idx, txt, restColor, yPix, appearA) {
      if (appearA <= 0.10) return;                        // label rides in with its fit
      var appear = ease(clamp((appearA - 0.10) / 0.30, 0, 1));
      var isActive = idx === activeIdx;
      // ink + full while active, blending to a faint resting label once superseded
      // or once phase 1 has ended (spot -> 0).
      ctx.globalAlpha = appear * memberFade * emphA(idx);
      ctx.fillStyle = (isActive && spot > 0.5) ? C.ink : restColor;
      ctx.fillText(txt, xr, yPix);
    }
    memLabel(0, 'ridge', GRAY1, slotY[0], aRidge);
    memLabel(1, 'bayes', GRAY1, slotY[1], aBayes);
    memLabel(2, 'forest', GRAY2, slotY[2], aForest);
    memLabel(3, 'boosting', BMUTED, slotY[3], aBoost);
    ctx.globalAlpha = 1;

    // ---- phase 2: weight bars fade in (real learned weights) ----
    var aWeights = clamp((p - 8.0) / 1.6, 0, 1);
    if (aWeights > 0) {
      ctx.globalAlpha = ease(aWeights);
      // real held-out test error (blend.json test_overall, deg F) appended to
      // each bar so a 0% weight reads as earned, not arbitrary: the linear
      // models are simply the least accurate of the four on unseen data.
      var bars = [
        { name: 'ridge', w: 0.00, err: '1.29', col: GRAY1 },
        { name: 'bayes', w: 0.00, err: '1.29', col: GRAY1 },
        { name: 'forest', w: 0.45, err: '1.19', col: GRAY2 },
        { name: 'boosting', w: 0.55, err: '1.12', col: BMUTED }
      ];
      var bx = m.X(0.04), bw = (m.X(0.42) - bx), bh = 7, bgap = 5;
      var by0 = pad.t + 6;
      ctx.font = MONO; ctx.textBaseline = 'alphabetic';
      for (var bi = 0; bi < bars.length; bi++) {
        var by = by0 + bi * (bh + bgap + 8);
        // track
        ctx.fillStyle = 'rgba(20,24,30,0.06)';
        ctx.fillRect(bx, by, bw, bh);
        // grown bar
        var grown = bw * bars[bi].w * ease(aWeights);
        ctx.fillStyle = bars[bi].col;
        ctx.fillRect(bx, by, grown, bh);
        // label + pct + real held-out error, so 0% reads as earned
        ctx.fillStyle = C.muted; ctx.textAlign = 'left';
        ctx.fillText(bars[bi].name, bx, by - 3);
        ctx.fillStyle = C.faint; ctx.textAlign = 'left';
        ctx.fillText(Math.round(bars[bi].w * 100) + '% · err ' + bars[bi].err + '°', bx + bw + 8, by + bh - 0.5);
      }
      ctx.globalAlpha = 1;
    }

    // ---- phase 3: composite line draws on top in full accent ----
    if (pComposite > 0) {
      ctx.globalAlpha = 1;
      poly(ctx, curve(BAKE.composite, ease(pComposite)), C.accent, 2.4);
      if (pComposite > 0.97) {
        ctx.globalAlpha = ease((pComposite - 0.97) / 0.03);
        ctx.fillStyle = C.accent; ctx.textAlign = 'left';
        ctx.fillText('composite', xr, pad.t + 60);
        ctx.globalAlpha = 1;
      }
    }
    ctx.globalAlpha = 1;
  }, BAKE_DUR);

  /* =====================================================================
     04  quantile band over scattered outcomes (gently breathing)
     ===================================================================== */
  var QPTS = (function () {
    var seed = 19; function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }
    var trend = function (x) { return 0.5 + 0.14 * Math.sin(x * 2.9 + 0.4); };
    var spread = function (x) { return 0.05 + 0.16 * x; };          // heteroscedastic: wider at right
    var pts = [];
    for (var i = 0; i < 80; i++) {
      var x = rnd();
      var g = (rnd() + rnd() + rnd() - 1.5) / 1.5;                  // ~normal
      pts.push([x, trend(x) + g * spread(x)]);
    }
    return { pts: pts, trend: trend };
  })();
  var QUANT_DUR = 2.0;
  loop('a-quant', function (s, t) {
    var pad = { l: 34, r: 56, t: 16, b: 24 };
    var m = mapper(s, pad, 0.10, 0.92), ctx = s.ctx;
    gridY(s, m, pad, [{ v: 0.78, t: '66°' }, { v: 0.5, t: '64°' }, { v: 0.22, t: '62°' }]);

    var trend = QPTS.trend;
    var g = ease(clamp(t / QUANT_DUR, 0, 1));                       // bands grow out once
    var outer = function (x) { return (0.09 + 0.16 * x) * g; }, inner = function (x) { return (0.045 + 0.08 * x) * g; };
    var N = 80, up = [], lo = [], ui = [], li = [], mid = [];
    for (var i = 0; i <= N; i++) {
      var x = i / N;
      up.push([m.X(x), m.Y(trend(x) + outer(x))]); lo.push([m.X(x), m.Y(trend(x) - outer(x))]);
      ui.push([m.X(x), m.Y(trend(x) + inner(x))]); li.push([m.X(x), m.Y(trend(x) - inner(x))]);
      mid.push([m.X(x), m.Y(trend(x))]);
    }
    fillBand(ctx, up, lo, C.band);
    fillBand(ctx, ui, li, C.band2);
    poly(ctx, mid, C.accent, 2.2);
    QPTS.pts.forEach(function (p) { dot(ctx, m.X(p[0]), m.Y(p[1]), 2, C.dot); });

    // right-edge labels fade in once the bands are grown; anchor to the
    // current band edges so they sit flush against the shaded region.
    if (g > 0.90) {
      ctx.globalAlpha = ease((g - 0.90) / 0.10);
      ctx.textAlign = 'left'; var xr = s.w - pad.r + 5;
      ctx.fillStyle = C.faint; ctx.fillText('P95', xr, m.Y(trend(1) + outer(1)) + 3);
      ctx.fillStyle = C.accent; ctx.fillText('P50', xr, m.Y(trend(1)) + 3);
      ctx.fillStyle = C.faint; ctx.fillText('P5', xr, m.Y(trend(1) - outer(1)) + 3);
      ctx.globalAlpha = 1;
    }
  }, QUANT_DUR);

  /* =====================================================================
     05  anchoring to the live observation (ping-pong raw <-> anchored)
     ===================================================================== */
  // raw appears (0..0.4s) -> pause (0.4..0.8s) -> slide raw->anchored (0.8..2.6s) -> freeze
  var ANCH_RAW = 0.4, ANCH_PAUSE = 0.8, ANCH_SLIDE = 1.8, ANCH_DUR = ANCH_PAUSE + ANCH_SLIDE;
  loop('a-anchor', function (s, t) {
    var pad = { l: 34, r: 58, t: 16, b: 26 };
    var m = mapper(s, pad, 0.18, 0.82), ctx = s.ctx;
    gridY(s, m, pad, [{ v: 0.72, t: '66°' }, { v: 0.5, t: '64°' }, { v: 0.28, t: '62°' }]);

    var R = function (x) { return 0.58 - 0.10 * x + 0.025 * Math.sin(x * 4 + 1); };
    var OBS = 0.40, delta = OBS - R(0);                              // raw(0) starts above the buoy dot
    var aRaw = ease(clamp(t / ANCH_RAW, 0, 1));                      // raw curve draws on
    var a = easeIO(clamp((t - ANCH_PAUSE) / ANCH_SLIDE, 0, 1));      // 0 raw -> 1 anchored
    var N = 80, raw = [], cor = [];
    for (var i = 0; i <= N; i++) {
      var x = (i / N) * aRaw;
      raw.push([m.X(x), m.Y(R(x))]);
      cor.push([m.X(x), m.Y(R(x) + delta * Math.exp(-x / 0.16) * a)]);
    }
    // vertical guide at x=0
    ctx.strokeStyle = C.grid; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(m.X(0), pad.t); ctx.lineTo(m.X(0), s.h - pad.b); ctx.stroke(); ctx.setLineDash([]);

    poly(ctx, raw, C.truth, 1.6, [5, 4]);
    poly(ctx, cor, C.accent, 2.2);

    dot(ctx, m.X(0), m.Y(OBS), 4, C.ink);
    ctx.textAlign = 'left'; ctx.fillStyle = C.muted;
    ctx.fillText('buoy now', m.X(0) + 8, m.Y(OBS) + 4);
    ctx.fillStyle = C.faint; ctx.fillText('raw model', m.X(0) + 8, m.Y(R(0)) - 8);

    // 'anchored' label fades in with the anchored phase, both labels legible at freeze
    if (a > 0.05) {
      ctx.globalAlpha = clamp(a, 0, 1);
      ctx.fillStyle = C.accent; ctx.fillText('anchored', m.X(0) + 8, m.Y(R(0) + delta) + 14);
      ctx.globalAlpha = 1;
    }
  }, ANCH_DUR);

  /* =====================================================================
     06  four-model ensemble; disagreement auto-oscillates until slider used
     ===================================================================== */
  /* Interactive exception. One eased sweep low -> high -> medium over ~6s, then
     FREEZE. After the sweep the slider drives a single static re-render per
     input event (no running loop). The replay button replays the sweep. */
  (function ens() {
    var c = document.getElementById('a-ens');
    if (!c) return;
    var slider = document.getElementById('ens-slider'), label = document.getElementById('ens-label');
    // freq, phase, tilt per member (fixed waveforms)
    var W = [[2.9, 0.2, 0.45], [4.1, 1.4, -0.55], [2.3, 3.0, 0.15], [4.8, 0.8, -0.25]];
    var pad = { l: 34, r: 56, t: 16, b: 26 };
    var sync = makeFig(c);

    function render(d) {
      var s = sync(), m = mapper(s, pad, 0.16, 0.84), ctx = s.ctx;
      gridY(s, m, pad, [{ v: 0.74, t: '66°' }, { v: 0.5, t: '64°' }, { v: 0.26, t: '62°' }]);
      d = clamp(d, 0, 1);
      var base = function (x) { return 0.55 - 0.08 * x; };
      // at d=1 the widest member excursion stays inside [0.16,0.84]; spread max ~0.18
      var spread = function (x) { return 0.02 + 0.16 * x; };
      var N = 80, mem = [[], [], [], []], up = [], lo = [], mid = [];
      for (var i = 0; i <= N; i++) {
        var x = i / N, vals = [];
        for (var k = 0; k < 4; k++) {
          var w = W[k];
          var v = base(x) + d * spread(x) * (0.7 * Math.sin(x * w[0] + w[1]) + w[2] * x);
          mem[k].push([m.X(x), m.Y(v)]); vals.push(v);
        }
        var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
        var av = (vals[0] + vals[1] + vals[2] + vals[3]) / 4;
        up.push([m.X(x), m.Y(mx)]); lo.push([m.X(x), m.Y(mn)]); mid.push([m.X(x), m.Y(av)]);
      }
      fillBand(ctx, up, lo, C.band);
      for (k = 0; k < 4; k++) poly(ctx, mem[k], C.member, 1);
      poly(ctx, mid, C.accent, 2.2);

      // band-width readout at the right edge
      ctx.textAlign = 'left'; var xr = s.w - pad.r + 5;
      ctx.fillStyle = C.accent; ctx.fillText('mean', xr, m.Y(0.51) + 3);
      ctx.fillStyle = C.faint; ctx.fillText('band', xr, m.Y(0.51) + 17);

      if (label) label.textContent = 'weather-model disagreement: ' + (d < 1 / 3 ? 'low' : d < 2 / 3 ? 'medium' : 'high');
    }

    // sweep: 0 -> 1 over first 3s, 1 -> 0.5 over next 3s, eased; freeze at medium
    var SWEEP = 6.0;
    function dAt(t) {
      if (t < 3) return easeIO(t / 3);
      return 1 - easeIO((t - 3) / 3) * 0.5;             // ease 1.0 down to 0.5 (medium)
    }
    var timer = null, t0 = 0, done = false, frozen = true, started = false;
    function step() {
      var t = (now() - t0) / 1000;
      if (t >= SWEEP) { render(dAt(SWEEP)); done = true; frozen = false; timer = null;
        if (slider) slider.value = Math.round(dAt(SWEEP) * 100); return; }
      render(dAt(t));
      timer = window.setTimeout(step, 16);
    }
    function replay() {
      t0 = now(); done = false; frozen = false;
      if (timer == null) { timer = window.setTimeout(step, 0); }
    }
    new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting && !started) { started = true; t0 = now(); frozen = false; step(); }
      });
    }, { threshold: 0.35 }).observe(c);
    // after the sweep, the slider re-renders statically (single render per input)
    if (slider) slider.addEventListener('input', function () {
      if (timer != null) { window.clearTimeout(timer); timer = null; done = true; }
      render(clamp(+slider.value / 100, 0, 1));
    });
    window.addEventListener('resize', function () {
      if (done) render(slider ? clamp(+slider.value / 100, 0, 1) : dAt(SWEEP));
    });
    REGISTRY['a-ens'] = { replay: replay };
  })();

  /* =====================================================================
     07  walk-forward backtest: folds crossfade into one another
     ===================================================================== */
  var FOLDS = 9, FOLD_SECS = 1.0, WALK_DUR = FOLDS * FOLD_SECS;
  loop('a-walk', function (s, t) {
    var pad = { l: 16, r: 16, t: 44, b: 30 }, ctx = s.ctx;
    var x0 = pad.l, x1 = s.w - pad.r, yt = pad.t, yb = s.h - pad.b, bh = yb - yt;
    var X = function (v) { return x0 + v * (x1 - x0); };

    // timeline + year ticks 2016..2026
    var years = ['2016', '2018', '2020', '2022', '2024', '2026'];
    ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x0, yb + 0.5); ctx.lineTo(x1, yb + 0.5); ctx.stroke();
    ctx.fillStyle = C.faint; ctx.textAlign = 'center';
    years.forEach(function (yr, i) {
      var xx = X(i / (years.length - 1));
      ctx.beginPath(); ctx.moveTo(xx, yt); ctx.lineTo(xx, yb); ctx.stroke();
      ctx.fillText(yr, xx, s.h - 11);
    });

    // final summary frame: settle on the fold-9 layout, fully drawn, with a
    // centered receipt line above. Reached at t === WALK_DUR (and frozen there).
    var atEnd = t >= WALK_DUR - 0.0005;
    var fi, lp;
    if (atEnd) { fi = FOLDS - 1; lp = 1; }
    else { fi = Math.floor(t / FOLD_SECS) % FOLDS; lp = (t / FOLD_SECS) - Math.floor(t / FOLD_SECS); }

    // crossfade: each fold fades in over the first 0.18 and out over the last 0.18;
    // the final fold stays fully opaque (no fade-out) so the frozen frame is solid.
    var alpha = 1;
    if (lp < 0.18) alpha = lp / 0.18;
    else if (lp > 0.82 && !atEnd) alpha = (1 - lp) / 0.18;
    ctx.globalAlpha = clamp(alpha, 0, 1);

    var trainEnd = 0.24 + fi * 0.056, gap = 0.03, testW = 0.05;
    var grow = atEnd ? trainEnd : trainEnd * ease(clamp(lp / 0.45, 0, 1));

    // train block grows left->right
    ctx.fillStyle = 'rgba(18,87,160,0.13)'; ctx.fillRect(X(0), yt, X(grow) - X(0), bh);
    ctx.strokeStyle = C.accent; ctx.lineWidth = 1.3;
    ctx.strokeRect(X(0) + 0.5, yt + 0.5, Math.max(0, X(grow) - X(0) - 1), bh - 1);
    ctx.fillStyle = C.accent; ctx.textAlign = 'left'; ctx.fillText('train', X(0) + 6, yt - 9);

    // test block fades in after the gap, once training is grown
    if (atEnd || lp > 0.48) {
      var ta = atEnd ? 1 : ease(clamp((lp - 0.48) / 0.18, 0, 1));
      ctx.globalAlpha = clamp(alpha, 0, 1) * ta;
      var tx = trainEnd + gap;
      ctx.fillStyle = 'rgba(180,83,9,0.18)'; ctx.fillRect(X(tx), yt, X(tx + testW) - X(tx), bh);
      ctx.strokeStyle = C.amber; ctx.lineWidth = 1.3;
      ctx.strokeRect(X(tx) + 0.5, yt + 0.5, X(tx + testW) - X(tx) - 1, bh - 1);
      ctx.fillStyle = C.amber; ctx.textAlign = 'center'; ctx.fillText('test', X(tx + testW / 2), yt - 9);
      ctx.globalAlpha = clamp(alpha, 0, 1);

      // green check fades in last
      if (atEnd || lp > 0.66) {
        ctx.globalAlpha = clamp(alpha, 0, 1) * (atEnd ? 1 : ease(clamp((lp - 0.66) / 0.16, 0, 1)));
        ctx.fillStyle = C.green; ctx.textAlign = 'left';
        ctx.fillText('scored', X(tx + testW) + 8, yt + bh / 2 + 4);
        ctx.globalAlpha = clamp(alpha, 0, 1);
      }
    }

    ctx.globalAlpha = 1;
    ctx.fillStyle = C.muted; ctx.textAlign = 'right';
    ctx.fillText('fold ' + (fi + 1) + ' / 9', x1, yt - 9);

    // centered receipt line, fading in over the last fold and staying on freeze
    var sa = atEnd ? 1 : ease(clamp((t - (WALK_DUR - FOLD_SECS)) / (FOLD_SECS * 0.6), 0, 1));
    if (sa > 0.01) {
      ctx.globalAlpha = sa;
      ctx.fillStyle = C.ink; ctx.textAlign = 'center'; ctx.font = MONO;
      ctx.fillText('9 seasons replayed · 131,339 forecasts scored', (x0 + x1) / 2, 18);
      ctx.globalAlpha = 1;
    }
  }, WALK_DUR);

  /* =====================================================================
     04b  turning history into examples: a window glides over a fixed series,
     each pause emits one (inputs -> answer) row into a small table below.
     Plays through exactly 4 stops, then freezes with all 4 rows populated and
     the counter resting on 599,000+.
     ===================================================================== */
  (function windowFig() {
    // a fixed wiggly temperature series
    var series = function (x) { return 0.55 + 0.22 * Math.sin(x * 6.1) + 0.08 * Math.sin(x * 13 + 1.2); };
    // exactly 4 stops; window eases to each, pauses, emits one row
    var STOPS = 4, LEG = 0.95, DWELL = 0.65, SEG = LEG + DWELL;
    var WIN_DUR = STOPS * SEG;                          // ~6.4s, then freeze
    var winW = 0.15;                                    // window ~15% wide
    loop('a-window', function (s, t) {
      var ctx = s.ctx, w = s.w, h = s.h;
      var topPad = { l: 34, r: 56, t: 14, b: 6 };
      var midY = h * 0.46;                              // divide top series / bottom table
      var sh = midY - 6 - topPad.t;                     // top series occupies [topPad.t .. midY-6]
      var X = function (v) { return topPad.l + v * (w - topPad.l - topPad.r); };
      var Ys = function (v) { return topPad.t + (1 - v) * sh; };

      // faint grid (3 lines)
      ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
      [0.25, 0.55, 0.85].forEach(function (gv) { ctx.beginPath(); ctx.moveTo(topPad.l, Ys(gv)); ctx.lineTo(w - topPad.r, Ys(gv)); ctx.stroke(); });

      // the fixed series
      var N = 90, sp = [];
      for (var i = 0; i <= N; i++) { var x = i / N; sp.push([X(x), Ys(series(x))]); }
      poly(ctx, sp, C.ink, 1.6);

      // clamp the clock so the figure settles on the last stop and freezes there
      var tc = clamp(t, 0, WIN_DUR - 0.0005);
      var idx = Math.min(Math.floor(tc / SEG), STOPS - 1);
      var idxNext = Math.min(idx + 1, STOPS - 1);
      var local = (tc / SEG) - Math.floor(tc / SEG);
      var move = easeIO(clamp(local / (LEG / SEG), 0, 1));
      var stopX = function (k) { return 0.06 + (k / (STOPS - 1)) * 0.60; };   // left edge of window
      var wx = stopX(idx) + (stopX(idxNext) - stopX(idx)) * move;

      // translucent accent window
      ctx.fillStyle = 'rgba(18,87,160,0.10)';
      ctx.fillRect(X(wx), topPad.t, X(wx + winW) - X(wx), sh);
      ctx.strokeStyle = 'rgba(18,87,160,0.45)'; ctx.lineWidth = 1;
      ctx.strokeRect(X(wx) + 0.5, topPad.t + 0.5, X(wx + winW) - X(wx) - 1, sh - 1);

      // amber target dot at +24h ahead of the window's right edge
      var tgtX = wx + winW + 0.10;
      dot(ctx, X(tgtX), Ys(series(tgtX)), 3.2, C.amber);
      ctx.font = MONO; ctx.fillStyle = C.amber; ctx.textAlign = 'center';
      ctx.fillText('answer', X(tgtX), Ys(series(tgtX)) - 8);
      ctx.fillStyle = C.faint; ctx.textAlign = 'center';
      ctx.fillText('+24h', X(tgtX), Ys(series(tgtX)) + 14);

      // --- bottom mini-table: 4 fixed slots, one filled per completed stop ---
      var rowH = 22, tx = topPad.l, ty0 = midY + 18;
      var sq = 11, gap = 4;
      // how many rows are visible: each stop completes when its pause finishes.
      // filled = number of stops fully reached; the current stop's row fades in as
      // the window settles (move -> 1).
      for (var r = 0; r < STOPS; r++) {
        // row r is fully shown once the window has reached stop r and is settling.
        var rowAlpha = 0;
        if (r < idx) rowAlpha = 1;
        else if (r === idx) rowAlpha = move;            // current row fades in as we settle
        if (rowAlpha <= 0.001) continue;
        var ry = ty0 + r * rowH;
        ctx.globalAlpha = clamp(rowAlpha, 0, 1);

        // 5 accent input squares
        for (var c = 0; c < 5; c++) {
          ctx.fillStyle = 'rgba(18,87,160,0.16)';
          ctx.strokeStyle = 'rgba(18,87,160,0.45)'; ctx.lineWidth = 1;
          var cx = tx + c * (sq + gap);
          ctx.fillRect(cx, ry, sq, sq); ctx.strokeRect(cx + 0.5, ry + 0.5, sq - 1, sq - 1);
        }
        var arrowX = tx + 5 * (sq + gap) + 4;
        // arrow ->
        ctx.strokeStyle = C.faint; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.moveTo(arrowX, ry + sq / 2); ctx.lineTo(arrowX + 16, ry + sq / 2); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(arrowX + 16, ry + sq / 2); ctx.lineTo(arrowX + 11, ry + sq / 2 - 3); ctx.moveTo(arrowX + 16, ry + sq / 2); ctx.lineTo(arrowX + 11, ry + sq / 2 + 3); ctx.stroke();
        // amber answer square
        var ansX = arrowX + 22;
        ctx.fillStyle = 'rgba(180,83,9,0.18)'; ctx.strokeStyle = 'rgba(180,83,9,0.55)';
        ctx.fillRect(ansX, ry, sq, sq); ctx.strokeRect(ansX + 0.5, ry + 0.5, sq - 1, sq - 1);
      }
      ctx.globalAlpha = 1;

      // label the inputs / answer once (static labels)
      ctx.font = MONO; ctx.fillStyle = C.faint; ctx.textAlign = 'left';
      ctx.fillText('inputs (46)', tx, ty0 - 6);
      ctx.fillStyle = C.amber;
      ctx.fillText('answer', tx + 5 * (sq + gap) + 26, ty0 - 6);

      // counter bottom-right rests on 599,000+
      ctx.font = MONO; ctx.fillStyle = C.faint; ctx.textAlign = 'right';
      ctx.fillText('rows: 599,000+', w - topPad.r, h - 5);
    }, WIN_DUR);
  })();

  /* =====================================================================
     05b  what one tree does: best-split sweep over a seeded scatter.
     A vertical line sweeps x, drawing left-mean / right-mean segments and a
     live error readout; tracks the best (min SSE) split and settles there.
     ===================================================================== */
  var TREE = (function build() {
    var seed = 41; function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }
    var pts = [], N = 50;
    // step-ish trend: low for x<~0.6, high above, plus noise
    for (var i = 0; i < N; i++) {
      var x = rnd();
      var base = x < 0.6 ? 0.34 : 0.66;
      var y = clamp(base + (rnd() - 0.5) * 0.22, 0.06, 0.94);
      pts.push([x, y]);
    }
    // sweep thresholds, find argmin SSE split
    function evalSplit(thr) {
      var lS = 0, lN = 0, rS = 0, rN = 0;
      for (var j = 0; j < N; j++) { if (pts[j][0] < thr) { lS += pts[j][1]; lN++; } else { rS += pts[j][1]; rN++; } }
      if (!lN || !rN) return null;
      var lM = lS / lN, rM = rS / rN, sse = 0;
      for (j = 0; j < N; j++) { var d = pts[j][1] - (pts[j][0] < thr ? lM : rM); sse += d * d; }
      return { thr: thr, lM: lM, rM: rM, mse: sse / N };
    }
    var best = null;
    for (var th = 0.10; th <= 0.90; th += 0.005) { var e = evalSplit(th); if (e && (!best || e.mse < best.mse)) best = e; }
    return { pts: pts, N: N, evalSplit: evalSplit, best: best };
  })();

  (function treeFig() {
    var label = document.getElementById('tree-label');
    var SWEEP = 3.0, BACK = 0.8, TREE_DUR = SWEEP + BACK;
    var pad = { l: 30, r: 64, t: 16, b: 24 };
    loop('a-tree', function (s, t) {
      var ctx = s.ctx;
      var m = mapper(s, pad, 0, 1);
      var p = clamp(t / TREE_DUR, 0, 1);               // 0..1 over sweep+settle

      // grid
      gridY(s, m, pad, [{ v: 0.8, t: '' }, { v: 0.5, t: '' }, { v: 0.2, t: '' }]);

      // scatter
      TREE.pts.forEach(function (pt) { dot(ctx, m.X(pt[0]), m.Y(pt[1]), 2.2, C.dot); });

      // first SWEEP is the sweep, the tail eases the line back to the best split.
      var sweepFrac = SWEEP / TREE_DUR;
      var thr, settling = false, settleP = 0;
      if (p <= sweepFrac) {
        var sp = ease(p / sweepFrac);                  // easeOut sweep 0..1
        thr = 0.10 + sp * 0.80;                        // 0.10..0.90
      } else {
        settling = true;
        settleP = easeIO((p - sweepFrac) / (1 - sweepFrac));   // easeInOut back to best
        thr = 0.90 + (TREE.best.thr - 0.90) * settleP;
      }
      var e = TREE.evalSplit(thr) || TREE.best;

      // best-so-far dashed marker (argmin over the whole domain, fixed)
      ctx.strokeStyle = 'rgba(18,87,160,0.30)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(m.X(TREE.best.thr), pad.t); ctx.lineTo(m.X(TREE.best.thr), s.h - pad.b); ctx.stroke(); ctx.setLineDash([]);

      // two mean segments
      poly(ctx, [[m.X(0), m.Y(e.lM)], [m.X(thr), m.Y(e.lM)]], C.ink, 2);
      poly(ctx, [[m.X(thr), m.Y(e.rM)], [m.X(1), m.Y(e.rM)]], C.ink, 2);

      // sweeping vertical line
      poly(ctx, [[m.X(thr), pad.t], [m.X(thr), s.h - pad.b]], C.accent, 2);

      // live threshold value travels with the moving line (during the sweep)
      if (!settling) {
        ctx.font = MONO; ctx.fillStyle = C.accent;
        // keep the floating value inside the plot: flip side near the right edge
        if (thr > 0.78) { ctx.textAlign = 'right'; ctx.fillText('x ' + thr.toFixed(2), m.X(thr) - 6, pad.t + 4); }
        else { ctx.textAlign = 'left'; ctx.fillText('x ' + thr.toFixed(2), m.X(thr) + 6, pad.t + 4); }
      }

      // live error readout, top-right
      ctx.font = MONO; ctx.textAlign = 'right'; ctx.fillStyle = C.muted;
      ctx.fillText('error: ' + e.mse.toFixed(3), s.w - pad.r + 56, pad.t + 4);

      // settled 'best question' label fades in as the line eases back to best
      if (settling) {
        ctx.globalAlpha = settleP;
        ctx.fillStyle = C.accent; ctx.textAlign = 'left';
        ctx.fillText('best question: x > ' + TREE.best.thr.toFixed(2), m.X(TREE.best.thr) + 6, s.h - pad.b - 8);
        ctx.globalAlpha = 1;
      }

      if (label) {
        if (settling) label.textContent = 'best split at x > ' + TREE.best.thr.toFixed(2) + ' · error ' + TREE.best.mse.toFixed(3);
        else label.textContent = 'trying x > ' + thr.toFixed(2) + ' · error ' + e.mse.toFixed(3);
      }
    }, TREE_DUR);
  })();

  /* =====================================================================
     10b  memorizing vs learning: a smooth curve that learns the shape and a
     wobbly curve that threads every train dot, then new hollow test dots
     reveal the memorizer's failure. RMSEs computed honestly.
     ===================================================================== */
  var OVERFIT = (function build() {
    // Seeded so the honest RMSEs are stable: pastMemo 0.00 / pastSmooth 0.06,
    // newMemo 0.31 / newSmooth 0.04. The memorizer hits every train point
    // exactly but wiggles hard between them; on new x it is far off.
    var seed = 44; function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }
    var trend = function (x) { return 0.50 + 0.20 * Math.sin(x * 3.2 + 0.5); };
    var NT = 11, WIG = 0.60, train = [];
    for (var i = 0; i < NT; i++) {
      var x = (i + 0.5) / NT;                          // evenly spread across [0,1]
      var y = clamp(trend(x) + (rnd() - 0.5) * 0.27, 0.12, 0.88);
      train.push([x, y]);
    }
    train.sort(function (a, b) { return a[0] - b[0]; });
    var res = train.map(function (p) { return p[1] - trend(p[0]); });   // train residual vs the true shape
    // test points: NEW x the model never saw, at the interval midpoints (where it wiggles
    // most), drawn honestly from the same trend with a little noise.
    var test = [];
    for (i = 0; i < train.length - 1 && test.length < 8; i++) {
      var xt = (train[i][0] + train[i + 1][0]) / 2;
      test.push([xt, clamp(trend(xt) + (rnd() - 0.5) * 0.11, 0.06, 0.94)]);
    }
    var smooth = function (x) { return trend(x); };
    // memorizing model: linear-interpolate the residual (so it hits each train point
    // exactly) plus an alternating half-sine bump that is zero at every node but large
    // in between. That is memorization: it explains each past point with structure that
    // does not generalize.
    function memo(x) {
      var p = train;
      if (x <= p[0][0]) return trend(x) + res[0];
      if (x >= p[p.length - 1][0]) return trend(x) + res[res.length - 1];
      var k = 0; while (k < p.length - 1 && p[k + 1][0] < x) k++;
      var u = (x - p[k][0]) / (p[k + 1][0] - p[k][0]);
      var lin = res[k] + (res[k + 1] - res[k]) * u;
      var bump = Math.sin(u * Math.PI) * WIG * (k % 2 ? -1 : 1) * 0.5;
      return trend(x) + lin + bump;
    }
    function rmse(model, set) {
      var se = 0; for (var j = 0; j < set.length; j++) { var d = model(set[j][0]) - set[j][1]; se += d * d; } return Math.sqrt(se / set.length);
    }
    return {
      train: train, test: test, trend: trend, smooth: smooth, memo: memo,
      pastSmooth: rmse(smooth, train), pastMemo: rmse(memo, train),
      newSmooth: rmse(smooth, test), newMemo: rmse(memo, test)
    };
  })();

  var OVERFIT_DUR = 8.0;
  loop('a-overfit', function (s, t) {
    var ctx = s.ctx;
    var pad = { l: 22, r: 16, t: 18, b: 22 };
    var m = mapper(s, pad, -0.12, 1.12);              // headroom for the wiggle
    var p = clamp(t / OVERFIT_DUR, 0, 1);             // single pass 0..1, then freeze

    // phase windows
    var aSmooth = ease(clamp(p / 0.22, 0, 1));         // smooth curve draws 0..0.22
    var aMemo = ease(clamp((p - 0.22) / 0.22, 0, 1));  // memo curve draws 0.22..0.44
    var aTest = ease(clamp((p - 0.52) / 0.18, 0, 1));  // test dots fade in 0.52..0.70

    gridY(s, m, pad, [{ v: 0.85, t: '' }, { v: 0.5, t: '' }, { v: 0.15, t: '' }]);

    var N = 140;
    // smooth (accent) curve, drawn progressively
    var smp = [];
    for (var i = 0; i <= N; i++) { var x = (i / N) * aSmooth; smp.push([m.X(x), m.Y(OVERFIT.smooth(x))]); }
    poly(ctx, smp, C.accent, 2.2);

    // memorizing (amber) curve, drawn progressively after the smooth one
    if (aMemo > 0.001) {
      var mmp = [];
      for (i = 0; i <= N; i++) { var xm = (i / N) * aMemo; mmp.push([m.X(xm), m.Y(OVERFIT.memo(xm))]); }
      poly(ctx, mmp, C.amber, 2);
    }

    // train dots (solid)
    OVERFIT.train.forEach(function (pt) { dot(ctx, m.X(pt[0]), m.Y(pt[1]), 2.6, C.dot); });

    // test dots (hollow circles, ink stroke, no fill) fade in
    if (aTest > 0.001) {
      ctx.globalAlpha = aTest;
      ctx.strokeStyle = C.ink; ctx.lineWidth = 1.3;
      OVERFIT.test.forEach(function (pt) {
        ctx.beginPath(); ctx.arc(m.X(pt[0]), m.Y(pt[1]), 3.2, 0, 7); ctx.stroke();
      });
      ctx.globalAlpha = 1;
    }

    // curve labels (placed in roomy corners)
    ctx.font = MONO;
    if (aMemo > 0.6) {
      ctx.globalAlpha = ease((aMemo - 0.6) / 0.4);
      ctx.textAlign = 'left';
      ctx.fillStyle = C.amber; ctx.fillText('memorizes the points', m.X(0.30), m.Y(1.06));
      ctx.fillStyle = C.accent; ctx.fillText('learns the shape', m.X(0.04), m.Y(-0.07));
      ctx.globalAlpha = 1;
    }

    // readouts, inside the top-left, right-aligned column would clash with the
    // curve, so anchor them to a clear strip at the left mid-height.
    var rx = m.X(0.02), yy = m.Y(0.42);
    ctx.textAlign = 'left'; ctx.font = MONO;
    ctx.fillStyle = C.amber; ctx.fillText('past error: ' + OVERFIT.pastMemo.toFixed(2), rx, yy);
    ctx.fillStyle = C.accent; ctx.fillText('past error: ' + OVERFIT.pastSmooth.toFixed(2), rx, yy + 14);
    if (aTest > 0.2) {
      ctx.globalAlpha = ease(clamp((aTest - 0.2) / 0.8, 0, 1));
      ctx.fillStyle = C.amber; ctx.fillText('new-data error: ' + OVERFIT.newMemo.toFixed(2), rx, yy + 32);
      ctx.fillStyle = C.accent; ctx.fillText('new-data error: ' + OVERFIT.newSmooth.toFixed(2), rx, yy + 46);
      ctx.globalAlpha = 1;
    }
    ctx.globalAlpha = 1;
  }, OVERFIT_DUR);

  /* =====================================================================
     10  THE WHOLE MACHINE: a full-width, four-column pipeline drawn once.
     Left to right: four data sources -> the real 46 inputs (seven groups,
     6/12/4/11/4/8/1) -> five quantile models x 34 weather futures = 170 runs
     -> one banded forecast. Plays a four-phase sequence (~17.5s) then freezes
     on the fully-assembled diagram with connectors resting at low alpha.

     Responsive: one canvas. Column x-bands and chip sizes are recomputed from
     the live width every frame. Below ~720px the chips drop their text and
     render as dots under each group header; the switch is automatic by width. */
  var PIPE = (function build() {
    // sources: index -> {title, sub}. order is the vertical stack in column 1.
    var sources = [
      { title: 'NDBC BUOY 45174', sub: 'water, waves, wind, every 10 min' },
      { title: 'ERA5 REANALYSIS', sub: 'ten years of hourly weather' },
      { title: 'GEFS + 3 MODELS', sub: '34 weather futures, next 8 days' },
      { title: 'THE CLOCK', sub: 'season and hour of day' }
    ];
    // seven feature groups, exact production counts; src is the source index
    // that lights when the group lands. chips are short human labels.
    var groups = [
      { name: 'BUOY NOW', src: 0, chips: [
        'water temp', 'wave ht', 'air temp', 'wind spd', 'gusts', 'pressure'] },
      { name: 'WATER MEMORY', src: 0, chips: [
        'wtr 1h', 'wtr 2h', 'wtr 3h', 'wtr 6h', 'wtr 12h', 'wtr 24h',
        'wav 1h', 'wav 2h', 'wav 3h', 'wav 6h', 'wav 12h', 'wav 24h'] },
      { name: 'TRENDS', src: 0, chips: [
        '6h wtr chg', '24h wtr chg', 'air - wtr', '3h pres chg'] },
      { name: 'WIND VECTORS', src: 0, chips: [
        'wind E-W', 'wind N-S', 'EW 6h', 'EW 12h', 'EW 24h',
        'NS 6h', 'NS 12h', 'NS 24h', 'spd 6h', 'spd 12h', 'spd 24h'] },
      { name: 'CLOCKS', src: 3, chips: [
        'season sin', 'season cos', 'hour sin', 'hour cos'] },
      { name: 'COMING WEATHER', src: 2, chips: [
        'wind E-W', 'wind N-S', 'speed', 'air temp', 'sun', 'gusts', 'dryness', 'air - wtr'] },
      { name: 'THE QUESTION', src: 3, chips: ['lead ahead'] }
    ];
    var total = 0; groups.forEach(function (g) { total += g.chips.length; });   // === 46
    return { sources: sources, groups: groups, total: total };
  })();

  var PIPE_DUR = 17.5;
  loop('a-pipeline', function (s, t) {
    var ctx = s.ctx, w = s.w, h = s.h;
    var label = document.getElementById('pipeline-label');
    var narrow = w < 720;                                // chips degrade to dots

    // phase boundaries (seconds)
    var P1 = 3.0, P2 = 9.5, P3 = 13.5, P4 = PIPE_DUR;    // ends of phases 1..4

    // ---- four column x-bands from live width ----
    var padX = Math.max(8, w * 0.012);
    var gap = Math.max(10, w * 0.018);
    var usable = w - padX * 2 - gap * 3;
    // weights: sources, inputs(widest), models, forecast
    var cw = [0.20, 0.36, 0.22, 0.22];
    var col = [], cx = padX;
    for (var ci = 0; ci < 4; ci++) {
      var cwidth = usable * cw[ci];
      col.push({ x: cx, w: cwidth, cx: cx + cwidth / 2 });
      cx += cwidth + gap;
    }
    var topY = 14, botY = h - 14;

    // ---- helpers ----
    function rrect(x, y, ww, hh, r) {
      r = Math.min(r, ww / 2, hh / 2);
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + ww, y, x + ww, y + hh, r);
      ctx.arcTo(x + ww, y + hh, x, y + hh, r);
      ctx.arcTo(x, y + hh, x, y, r);
      ctx.arcTo(x, y, x + ww, y, r);
      ctx.closePath();
    }
    // a flowing pulse along a horizontal-ish path from (x0,y0) to (x1,y1).
    // phase in [0,1]; draws a faint resting line plus a moving bright dot when active.
    function connect(x0, y0, x1, y1, lit, restA) {
      ctx.strokeStyle = 'rgba(18,87,160,' + (0.06 + 0.10 * restA).toFixed(3) + ')';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      var mx = (x0 + x1) / 2;
      ctx.bezierCurveTo(mx, y0, mx, y1, x1, y1);
      ctx.stroke();
      if (lit > 0 && lit < 1) {
        // moving pulse (sample the bezier)
        var u = lit, iu = 1 - u;
        var bx = iu * iu * iu * x0 + 3 * iu * iu * u * mx + 3 * iu * u * u * mx + u * u * u * x1;
        var by = iu * iu * iu * y0 + 3 * iu * iu * u * y0 + 3 * iu * u * u * y1 + u * u * u * y1;
        ctx.globalAlpha = 1 - Math.abs(0.5 - u) * 1.2;
        dot(ctx, bx, by, 2.4, C.accent);
        ctx.globalAlpha = 1;
      }
    }

    // =====================================================================
    // PHASE 1: source cards fade in, staggered
    // =====================================================================
    var srcN = PIPE.sources.length;
    var srcCardH = Math.min(74, (botY - topY - (srcN - 1) * 10) / srcN);
    var srcGap = (botY - topY - srcCardH * srcN) / (srcN - 1);
    var srcBox = [];                                     // remember positions for connectors
    for (var si = 0; si < srcN; si++) {
      var sy = topY + si * (srcCardH + srcGap);
      var sa = ease(clamp((t - si * 0.5) / 0.9, 0, 1));  // staggered fade-in over phase 1
      srcBox.push({ x: col[0].x, y: sy, w: col[0].w, h: srcCardH, cx: col[0].x + col[0].w, cy: sy + srcCardH / 2 });
      if (sa <= 0.001) continue;
      ctx.globalAlpha = sa;
      ctx.fillStyle = '#fbfbf9';
      rrect(col[0].x, sy, col[0].w, srcCardH, 7); ctx.fill();
      ctx.strokeStyle = 'rgba(18,87,160,0.30)'; ctx.lineWidth = 1;
      rrect(col[0].x + 0.5, sy + 0.5, col[0].w - 1, srcCardH - 1, 7); ctx.stroke();
      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      ctx.font = MONO; ctx.fillStyle = C.ink;
      ctx.fillText(fitMono(ctx, PIPE.sources[si].title, col[0].w - 14), col[0].x + 8, sy + 18);
      ctx.fillStyle = C.muted; ctx.font = '9px "IBM Plex Mono", monospace';
      wrapMono(ctx, PIPE.sources[si].sub, col[0].x + 8, sy + 32, col[0].w - 14, 11);
      ctx.font = MONO;
      ctx.globalAlpha = 1;
    }

    // =====================================================================
    // PHASE 2: the 46 inputs panel. Seven groups land one by one.
    // =====================================================================
    var gpsN = PIPE.groups.length;
    // group land schedule: first group lands at P1, then ~ (P2-P1)/gpsN apart
    var slot = (P2 - P1) / gpsN;
    function groupLand(gi) {
      // returns appearance 0..1 for group gi (0 before, eased in over ~0.55*slot)
      var ts = P1 + gi * slot;
      return ease(clamp((t - ts) / (slot * 0.6), 0, 1));
    }
    // count inputs revealed so far for the running counter
    var shown = 0;
    for (var gc = 0; gc < gpsN; gc++) {
      var la = groupLand(gc);
      if (la >= 0.999) shown += PIPE.groups[gc].chips.length;
      else if (la > 0) shown += Math.round(PIPE.groups[gc].chips.length * la);
    }
    if (t < P1) shown = 0;
    var countN = Math.min(PIPE.total, shown);

    // panel frame
    var panel = col[1];
    var panelTop = topY, panelBot = botY;
    var panelAppear = ease(clamp((t - (P1 - 0.4)) / 0.6, 0, 1));
    if (panelAppear > 0.001) {
      ctx.globalAlpha = 0.5 * panelAppear;
      ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
      rrect(panel.x + 0.5, panelTop + 0.5, panel.w - 1, panelBot - panelTop - 1, 8); ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // lay out the 7 groups vertically inside the panel. Each group is a header
    // line plus a wrapped grid of chips. Heights are proportional to row count.
    var innerX = panel.x + 7, innerW = panel.w - 14;
    var perRow = narrow ? 8 : (innerW > 250 ? 6 : 5);   // chips per row
    // precompute rows per group and total vertical units
    var rowsArr = PIPE.groups.map(function (g) { return Math.ceil(g.chips.length / perRow); });
    var headerH = 13, chipH = narrow ? 9 : 15, chipGap = 3, groupGap = narrow ? 8 : 7;
    // compute total height needed; scale chipH down if it overflows
    function groupHeight(rows) { return headerH + rows * (chipH + chipGap); }
    var totalH = 0; rowsArr.forEach(function (r) { totalH += groupHeight(r); });
    totalH += groupGap * (gpsN - 1);
    var avail = panelBot - panelTop - 12;
    var scaleY = totalH > avail ? avail / totalH : 1;
    var gy = panelTop + 6;
    var chipCenters = [];                                // remember a representative point per group for connectors
    for (var gi2 = 0; gi2 < gpsN; gi2++) {
      var g = PIPE.groups[gi2];
      var rows = rowsArr[gi2];
      var gh = groupHeight(rows) * scaleY;
      var la2 = groupLand(gi2);
      var groupCY = gy + gh / 2;
      chipCenters.push({ x: panel.x, y: groupCY, src: g.src });
      if (la2 > 0.001) {
        ctx.globalAlpha = la2;
        // header in faint caps
        ctx.fillStyle = C.faint; ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
        ctx.fillText(g.name + ' (' + g.chips.length + ')', innerX, gy + 9 * scaleY + 1);
        // chips
        var cTop = gy + headerH * scaleY;
        var thisChipH = chipH * scaleY;
        var chipW = (innerW - (perRow - 1) * chipGap) / perRow;
        for (var k = 0; k < g.chips.length; k++) {
          var cr = Math.floor(k / perRow), cc = k % perRow;
          var chx = innerX + cc * (chipW + chipGap);
          var chy = cTop + cr * (thisChipH + chipGap * scaleY);
          // staggered chip pop within the group
          var ca = ease(clamp((la2 - k / g.chips.length * 0.5) / 0.5, 0, 1));
          if (ca <= 0.01) continue;
          ctx.globalAlpha = la2 * ca;
          if (narrow) {
            // degrade: dot only
            dot(ctx, chx + chipW / 2, chy + thisChipH / 2, 2.2, 'rgba(18,87,160,0.55)');
          } else {
            ctx.fillStyle = 'rgba(18,87,160,0.08)';
            rrect(chx, chy, chipW, thisChipH, 3); ctx.fill();
            ctx.strokeStyle = 'rgba(18,87,160,0.32)'; ctx.lineWidth = 1;
            rrect(chx + 0.5, chy + 0.5, chipW - 1, thisChipH - 1, 3); ctx.stroke();
            ctx.fillStyle = C.muted; ctx.font = '9px "IBM Plex Mono", monospace';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(fitMono(ctx, g.chips[k], chipW - 4), chx + chipW / 2, chy + thisChipH / 2 + 0.5);
            ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
          }
        }
        ctx.globalAlpha = 1;
      }
      gy += gh + groupGap * scaleY;
    }
    ctx.font = MONO;

    // ---- connectors: sources -> their group(s) during phase 2 ----
    // light each group's connector briefly as it lands.
    for (var gi3 = 0; gi3 < gpsN; gi3++) {
      var ts2 = P1 + gi3 * slot;
      var lit = clamp((t - ts2) / (slot * 0.9), 0, 1);   // pulse travels as group lands
      var src = srcBox[PIPE.groups[gi3].src];
      var cc2 = chipCenters[gi3];
      var restA = groupLand(gi3) >= 0.999 ? 1 : groupLand(gi3);
      if (groupLand(gi3) > 0.001 || (lit > 0 && lit < 1)) {
        connect(src.cx, src.cy, cc2.x, cc2.y, (t > ts2 && t < ts2 + slot * 0.9) ? lit : 1, restA);
      }
    }

    // running counter, top-right corner of the panel
    if (t >= P1 - 0.3) {
      ctx.font = MONO; ctx.fillStyle = C.muted; ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
      ctx.fillText('inputs: ' + countN + ' / 46', panel.x + panel.w, panelTop - 3 < 8 ? 10 : panelTop + 9);
      ctx.textAlign = 'left';
    }

    // =====================================================================
    // PHASE 3: the models. Funnel the 46-chip panel into five quantile cards,
    // then a x34 multiplier badge and a tally counting up to 170.
    // =====================================================================
    var mcol = col[2];
    var labels = ['P5', 'P25', 'P50', 'P75', 'P95'];
    var mN = labels.length;
    var mAppear = ease(clamp((t - P2) / 1.0, 0, 1));     // cards fade in at start of phase 3
    // models stack occupies the upper ~62% of the column; multiplier + tally below
    var mTop = topY + 18, mStackBot = topY + (botY - topY) * 0.60;
    var mCardH = Math.min(34, (mStackBot - mTop - (mN - 1) * 9) / mN);
    var mGap = (mStackBot - mTop - mCardH * mN) / (mN - 1);
    var mBox = [];
    for (var mi = 0; mi < mN; mi++) {
      var my = mTop + mi * (mCardH + mGap);
      mBox.push({ x: mcol.x, y: my, w: mcol.w, h: mCardH, cx: mcol.cx, cy: my + mCardH / 2, lx: mcol.x, rx: mcol.x + mcol.w });
    }
    // funnel connectors: from the input panel right edge into each model card.
    // converging lines with traveling pulses during early phase 3.
    if (t >= P2 - 0.2) {
      var funnelLit = clamp((t - P2) / 1.4, 0, 1);
      var srcMid = { x: panel.x + panel.w, y: (panelTop + panelBot) / 2 };
      for (var mi2 = 0; mi2 < mN; mi2++) {
        var rest = mAppear;
        connect(srcMid.x, srcMid.y, mBox[mi2].lx, mBox[mi2].cy,
          (t < P2 + 1.4) ? ((funnelLit + mi2 * 0.04) % 1) : 1, rest);
      }
    }
    // 34 thin gray future-lines fanning THROUGH the model stack (appear mid phase 3)
    var fanAppear = ease(clamp((t - (P2 + 1.6)) / 1.2, 0, 1));
    if (fanAppear > 0.001) {
      ctx.globalAlpha = 0.5 * fanAppear;
      ctx.strokeStyle = C.member; ctx.lineWidth = 0.6;
      var fL = mcol.x - 6, fR = mcol.x + mcol.w + 6;
      var fanCount = Math.round(34 * fanAppear);
      for (var fi = 0; fi < fanCount; fi++) {
        var fy0 = mTop + (fi / 33) * (mStackBot - mTop);
        var fy1 = mTop + ((33 - fi) / 33) * (mStackBot - mTop);
        ctx.beginPath(); ctx.moveTo(fL, fy0); ctx.lineTo(fR, fy1); ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    // model cards on top of the fan
    if (mAppear > 0.001) {
      for (var mi3 = 0; mi3 < mN; mi3++) {
        var b = mBox[mi3];
        var pa = ease(clamp((t - P2 - mi3 * 0.12) / 0.8, 0, 1));
        if (pa <= 0.01) continue;
        ctx.globalAlpha = pa;
        ctx.fillStyle = '#ffffff';
        rrect(b.x, b.y, b.w, b.h, 6); ctx.fill();
        ctx.strokeStyle = mi3 === 2 ? C.accent : 'rgba(18,87,160,0.35)';
        ctx.lineWidth = mi3 === 2 ? 1.6 : 1;
        rrect(b.x + 0.5, b.y + 0.5, b.w - 1, b.h - 1, 6); ctx.stroke();
        ctx.fillStyle = mi3 === 2 ? C.accent : C.ink; ctx.font = MONO;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(labels[mi3], b.cx, b.cy + 0.5);
        ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
        ctx.globalAlpha = 1;
      }
      // sublabel under the stack
      ctx.globalAlpha = ease(clamp((t - P2 - 0.4) / 0.8, 0, 1));
      ctx.fillStyle = C.faint; ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      wrapMono(ctx, 'five quantile regressors, each a stack of trees',
        mcol.cx, mStackBot + 14, mcol.w + 8, 11, true);
      ctx.font = MONO; ctx.textAlign = 'left'; ctx.globalAlpha = 1;
    }
    // multiplier badge + tally, lower part of the column
    var badgeAppear = ease(clamp((t - (P2 + 1.4)) / 0.9, 0, 1));
    if (badgeAppear > 0.001) {
      var bgy = mStackBot + 34;
      ctx.globalAlpha = badgeAppear;
      var btxt = 'x 34 weather futures';
      ctx.font = MONO; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      var bwid = ctx.measureText(btxt).width + 16;
      var bxl = mcol.cx - bwid / 2;
      ctx.fillStyle = 'rgba(180,83,9,0.10)';
      rrect(bxl, bgy - 9, bwid, 18, 5); ctx.fill();
      ctx.strokeStyle = 'rgba(180,83,9,0.5)'; ctx.lineWidth = 1;
      rrect(bxl + 0.5, bgy - 8.5, bwid - 1, 17, 5); ctx.stroke();
      ctx.fillStyle = C.amber; ctx.fillText(btxt, mcol.cx, bgy + 0.5);
      ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
      ctx.globalAlpha = 1;

      // tally counts up to 170 (= 5 x 34)
      var tallyP = ease(clamp((t - (P2 + 1.8)) / 1.4, 0, 1));
      var tally = Math.round(170 * tallyP);
      ctx.globalAlpha = ease(clamp((t - (P2 + 1.8)) / 0.6, 0, 1));
      ctx.fillStyle = C.ink; ctx.font = MONO; ctx.textAlign = 'center';
      ctx.fillText(tally + ' model runs', mcol.cx, bgy + 30);
      ctx.fillStyle = C.muted;
      ctx.fillText('per forecast hour', mcol.cx, bgy + 44);
      ctx.textAlign = 'left'; ctx.globalAlpha = 1;
    }

    // =====================================================================
    // PHASE 4: the forecast. The 170 runs converge into a mini banded fan.
    // =====================================================================
    var fcol = col[3];
    var fAppear = ease(clamp((t - P3) / (P4 - P3) * 1.05, 0, 1));   // draw-out 0..1
    // funnel from model stack into the forecast fan
    if (t >= P3 - 0.2) {
      var mMid = { x: mcol.x + mcol.w, y: (mTop + mStackBot) / 2 };
      var fMid = { x: fcol.x, y: (topY + botY) * 0.5 };
      var conLit = clamp((t - P3) / 1.2, 0, 1);
      connect(mMid.x, mMid.y, fMid.x, fMid.y, (t < P3 + 1.2) ? conLit : 1, fAppear);
    }
    if (fAppear > 0.001) {
      // mini fan: reuse the a-fan approach at small scale inside the forecast column
      var fpadT = topY + 60, fpadB = botY - 70;
      var fx0 = fcol.x + 4, fx1 = fcol.x + fcol.w - 4;
      var fih = fpadB - fpadT;
      var fX = function (x) { return fx0 + x * (fx1 - fx0); };
      var fY = function (v) { return fpadB - v * fih; };   // v in 0..1 (band space)
      var med = function (x) { return 0.62 - 0.34 * x + 0.06 * Math.sin(x * 4.6 + 0.6); };
      var hw = function (x) { return 0.04 + 0.30 * Math.pow(x, 1.1); };
      var hwi = function (x) { return hw(x) * 0.5; };
      var Np = 60, up = [], lo = [], ui = [], li = [], mid = [];
      for (var i = 0; i <= Np; i++) {
        var x = (i / Np) * fAppear;
        up.push([fX(x), fY(med(x) + hw(x))]); lo.push([fX(x), fY(med(x) - hw(x))]);
        ui.push([fX(x), fY(med(x) + hwi(x))]); li.push([fX(x), fY(med(x) - hwi(x))]);
        mid.push([fX(x), fY(med(x))]);
      }
      fillBand(ctx, up, lo, C.band);
      fillBand(ctx, ui, li, C.band2);
      poly(ctx, mid, C.accent, 2.2);
      // anchored 'now' dot at the left
      dot(ctx, fX(0), fY(med(0)), 3.5, C.ink);
      ctx.fillStyle = C.muted; ctx.font = MONO; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      ctx.fillText('now', fX(0) + 6, fY(med(0)) - 8);
      // edge labels once drawn
      if (fAppear > 0.9) {
        ctx.globalAlpha = ease((fAppear - 0.9) / 0.1);
        var fxr = fx1 + 3;
        ctx.fillStyle = C.faint; ctx.fillText('P95', fxr, fY(med(1) + hw(1)) + 3);
        ctx.fillStyle = C.accent; ctx.fillText('P50', fxr, fY(med(1)) + 3);
        ctx.fillStyle = C.faint; ctx.fillText('P5', fxr, fY(med(1) - hw(1)) + 3);
        ctx.globalAlpha = 1;
      }
      // caption under the fan
      ctx.globalAlpha = ease(clamp((t - P3 - 0.5) / 0.8, 0, 1));
      ctx.fillStyle = C.faint; ctx.font = '9px "IBM Plex Mono", monospace'; ctx.textAlign = 'center';
      wrapMono(ctx, 'one hourly forecast, bands calibrated on nine seasons',
        (fx0 + fx1) / 2, fpadB + 18, fcol.w + 8, 11, true);
      ctx.font = MONO; ctx.textAlign = 'left'; ctx.globalAlpha = 1;
    }

    // ---- caption phase label ----
    if (label) {
      var msg;
      if (t < P1) msg = 'reading the instruments';
      else if (t < P2) msg = 'assembling the 46 inputs';
      else if (t < P3) msg = 'running 170 models';
      else if (t < P4 - 0.01) msg = 'one banded forecast';
      else msg = 'raw readings in, a banded forecast out, every hour';
      label.textContent = msg;
    }
  }, PIPE_DUR);

  /* small text helpers used by the pipeline figure (mono only) */
  function fitMono(ctx, txt, maxW) {
    if (ctx.measureText(txt).width <= maxW) return txt;
    var s = txt;
    while (s.length > 1 && ctx.measureText(s + '…').width > maxW) s = s.slice(0, -1);
    return s + '…';
  }
  function wrapMono(ctx, txt, cx, y, maxW, lineH, centered) {
    var words = txt.split(' '), line = '', lines = [];
    for (var i = 0; i < words.length; i++) {
      var test = line ? line + ' ' + words[i] : words[i];
      if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = words[i]; }
      else line = test;
    }
    if (line) lines.push(line);
    var prevAlign = ctx.textAlign;
    if (centered) ctx.textAlign = 'center';
    for (i = 0; i < lines.length; i++) ctx.fillText(lines[i], cx, y + i * lineH);
    ctx.textAlign = prevAlign;
    return lines.length;
  }

  /* =====================================================================
     wire every caption replay button to its figure (boost + ens are wired at
     their own definitions; this covers the generic-loop figures).
     ===================================================================== */
  [
    ['a-fan', 'replay-fan'], ['a-window', 'replay-window'],
    ['a-tree', 'replay-tree'], ['a-bakeoff', 'replay-bakeoff'], ['a-quant', 'replay-quant'],
    ['a-anchor', 'replay-anchor'], ['a-ens', 'replay-ens'], ['a-overfit', 'replay-overfit'],
    ['a-walk', 'replay-walk'], ['a-pipeline', 'replay-pipeline']
  ].forEach(function (pair) { wireReplay(pair[0], pair[1]); });
})();
