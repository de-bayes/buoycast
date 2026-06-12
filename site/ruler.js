/* Making-Software ruler rail: ticks, proportional section labels, scroll
   cursor with fraction readout. Pages set window.MS_SECTIONS first. */
    (function () {
      var rail = document.getElementById('ms-ruler');
      if (!rail) return;
      var ticksEl = document.getElementById('ms-ruler-ticks');
      var labelsEl = document.getElementById('ms-ruler-labels');
      var cursor = document.getElementById('ms-ruler-cursor');
      var fracEl = document.getElementById('ms-ruler-frac');

      // section id -> short mono label, set per page before this script loads
      var SECTIONS = window.MS_SECTIONS || [];

      // fine ticks down the whole rail height (one every ~14px), built once
      var TICK_N = 56;
      var tickFrag = document.createDocumentFragment();
      for (var i = 0; i <= TICK_N; i++) {
        var tk = document.createElement('div');
        tk.className = 'ms-ruler__tick' + (i % 5 === 0 ? ' is-major' : '');
        tk.style.top = (i / TICK_N * 100) + '%';
        tickFrag.appendChild(tk);
      }
      ticksEl.appendChild(tickFrag);

      // build label nodes (positions set in layout())
      var labelNodes = [];
      SECTIONS.forEach(function (sec) {
        var el = document.getElementById(sec[0]);
        if (!el) return;
        var a = document.createElement('a');
        a.className = 'ms-ruler__label';
        a.href = '#' + sec[0];
        a.textContent = sec[1];
        a.addEventListener('click', function (ev) {
          ev.preventDefault();
          var target = document.getElementById(sec[0]);
          if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        labelsEl.appendChild(a);
        labelNodes.push({ el: el, node: a });
      });

      function docHeight() {
        return Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
      }

      // place each label at the vertical fraction of its section's top in the
      // doc, skipping hidden sections, then resolve collisions so every label
      // sits on its own line with breathing room
      var MIN_GAP = 15;
      function layout() {
        var total = docHeight();
        var railH = rail.getBoundingClientRect().height;
        if (railH < 50) return;  // rail hidden (narrow viewport); nothing to place
        var placed = [];
        labelNodes.forEach(function (rec) {
          var rect = rec.el.getBoundingClientRect();
          var visible = rec.el.offsetParent !== null && rect.height > 2;
          rec.node.style.display = visible ? '' : 'none';
          if (!visible) return;
          var top = rect.top + window.scrollY;
          var frac = total > 0 ? top / total : 0;
          placed.push({ rec: rec, px: frac * railH });
        });
        // top-down pass: push collisions downward
        for (var i = 1; i < placed.length; i++) {
          if (placed[i].px < placed[i - 1].px + MIN_GAP) {
            placed[i].px = placed[i - 1].px + MIN_GAP;
          }
        }
        // clamp the tail inside the rail and resolve upward if needed
        if (placed.length) {
          var last = placed[placed.length - 1];
          if (last.px > railH - 4) last.px = railH - 4;
          for (var k = placed.length - 2; k >= 0; k--) {
            if (placed[k].px > placed[k + 1].px - MIN_GAP) {
              placed[k].px = placed[k + 1].px - MIN_GAP;
            }
          }
        }
        placed.forEach(function (p) { p.rec.node.style.top = p.px + 'px'; });
        update();
      }

      // sections can reveal late (the backtest card unhides once stats load);
      // re-run layout when any registered section's hidden attribute flips
      if ('MutationObserver' in window) {
        var mo = new MutationObserver(function () { layout(); });
        labelNodes.forEach(function (rec) {
          mo.observe(rec.el, { attributes: true, attributeFilter: ['hidden', 'style', 'class'] });
        });
      }

      function update() {
        var max = docHeight() - window.innerHeight;
        var frac = max > 0 ? window.scrollY / max : 0;
        if (frac < 0) frac = 0; if (frac > 1) frac = 1;
        var railH = rail.getBoundingClientRect().height;
        var cursorPx = frac * railH;
        cursor.style.top = cursorPx + 'px';
        fracEl.textContent = frac.toFixed(2);
        labelNodes.forEach(function (rec) {
          if (rec.node.style.display === 'none') return;
          var lp = parseFloat(rec.node.style.top) || 0;
          rec.node.classList.toggle('is-faded', Math.abs(lp - cursorPx) < 13);
        });
        // highlight the label whose section is current
        var mid = window.scrollY + window.innerHeight * 0.33;
        var activeIdx = 0;
        for (var i = 0; i < labelNodes.length; i++) {
          var top = labelNodes[i].el.getBoundingClientRect().top + window.scrollY;
          if (top <= mid) activeIdx = i;
        }
        for (var j = 0; j < labelNodes.length; j++) {
          labelNodes[j].node.classList.toggle('is-active', j === activeIdx);
        }
      }

      // the rail is a scrollbar: click anywhere to jump, drag to scrub
      function fracFromPointer(e) {
        var rect = rail.getBoundingClientRect();
        var y = (e.touches ? e.touches[0].clientY : e.clientY) - rect.top;
        return Math.min(1, Math.max(0, y / rect.height));
      }
      function jumpTo(frac, smooth) {
        var max = docHeight() - window.innerHeight;
        window.scrollTo({ top: frac * max, behavior: smooth ? 'smooth' : 'auto' });
      }
      var scrubbing = false;
      rail.addEventListener('mousedown', function (e) {
        if (e.target.classList.contains('ms-ruler__label')) return;
        scrubbing = true; jumpTo(fracFromPointer(e), false); e.preventDefault();
      });
      window.addEventListener('mousemove', function (e) {
        if (scrubbing) jumpTo(fracFromPointer(e), false);
      });
      window.addEventListener('mouseup', function () { scrubbing = false; });
      rail.addEventListener('touchstart', function (e) {
        if (e.target.classList.contains('ms-ruler__label')) return;
        scrubbing = true; jumpTo(fracFromPointer(e), false);
      }, { passive: true });
      rail.addEventListener('touchmove', function (e) {
        if (scrubbing) jumpTo(fracFromPointer(e), false);
      }, { passive: true });
      rail.addEventListener('touchend', function () { scrubbing = false; });

      window.addEventListener('scroll', update, { passive: true });
      window.addEventListener('resize', layout);
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(layout);
      }
      // late relayout once canvases/images settle their heights
      window.addEventListener('load', function () { setTimeout(layout, 60); });
      layout();
    })();
