/* Laval Digital — scroll reveal + misc interactions. */
(function () {
  'use strict';

  // Reveal-on-scroll for section content (staggered per row).
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduce && 'IntersectionObserver' in window) {
    var targets = document.querySelectorAll(
      '.page-section .text-center, .page-section .row > div, footer.footer .row > div'
    );
    var seenRows = new WeakMap();
    targets.forEach(function (el) {
      el.classList.add('ld-reveal');
    });
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var el = entry.target;
          var row = el.parentElement;
          var n = seenRows.get(row) || 0;
          seenRows.set(row, n + 1);
          el.style.transitionDelay = Math.min(n, 5) * 85 + 'ms';
          el.classList.add('ld-in');
          io.unobserve(el);
        });
      },
      { threshold: 0.12, rootMargin: '0px 0px -6% 0px' }
    );
    targets.forEach(function (el) {
      io.observe(el);
    });
  }
  // Cursor parallax on the hero (desktop pointers only).
  (function () {
    var hero = document.querySelector('header.masthead .container');
    if (!hero || reduce) return;
    if (window.matchMedia('(pointer: coarse)').matches) return;
    var tx = 0,
      ty = 0,
      cx = 0,
      cy = 0,
      raf = null;
    function loop() {
      cx += (tx - cx) * 0.06;
      cy += (ty - cy) * 0.06;
      hero.style.transform =
        'translate3d(' + cx.toFixed(2) + 'px,' + cy.toFixed(2) + 'px,0)';
      if (Math.abs(tx - cx) > 0.05 || Math.abs(ty - cy) > 0.05) {
        raf = window.requestAnimationFrame(loop);
      } else {
        raf = null;
      }
    }
    document
      .querySelector('header.masthead')
      .addEventListener('mousemove', function (e) {
        var r = this.getBoundingClientRect();
        tx = ((e.clientX - r.left) / r.width - 0.5) * 18;
        ty = ((e.clientY - r.top) / r.height - 0.5) * 12;
        if (!raf) raf = window.requestAnimationFrame(loop);
      });
  })();

  // Gold scroll-progress hairline.
  (function () {
    var bar = document.createElement('div');
    bar.className = 'ld-progress';
    document.body.appendChild(bar);
    var ticking = false;
    function update() {
      var h = document.documentElement;
      var max = h.scrollHeight - h.clientHeight;
      var p = max > 0 ? h.scrollTop / max : 0;
      bar.style.transform = 'scaleX(' + p + ')';
      ticking = false;
    }
    window.addEventListener(
      'scroll',
      function () {
        if (!ticking) {
          window.requestAnimationFrame(update);
          ticking = true;
        }
      },
      { passive: true }
    );
    update();
  })();
})();
