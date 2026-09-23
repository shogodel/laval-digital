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
})();
