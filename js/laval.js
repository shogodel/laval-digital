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

  // Contact form: validate locally, show pending note.
  // ESPOCRM WIRING POINT: replace the body of this handler with a
  // fetch() POST to your EspoCRM Lead endpoint, then show
  // #submitSuccessMessage on 2xx or #submitErrorMessage otherwise.
  (function () {
    var form = document.getElementById('contactForm');
    if (!form) return;
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var ok = true;
      var name = document.getElementById('name');
      var email = document.getElementById('email');
      var phone = document.getElementById('phone');
      var message = document.getElementById('message');
      [[name, /.+/], [email, /.+@.+\..+/], [phone, /.+/], [message, /.+/]].forEach(
        function (pair) {
          var field = pair[0],
            rx = pair[1];
          var valid = field && rx.test(field.value.trim());
          field.classList.toggle('is-invalid', !valid);
          if (!valid) ok = false;
        }
      );
      if (!ok) return;
      document.getElementById('submitSuccessMessage').classList.remove('d-none');
      document.getElementById('submitErrorMessage').classList.add('d-none');
      form.querySelectorAll('.form-control').forEach(function (f) {
        f.value = '';
      });
    });
  })();

  // Card spotlight follows the cursor (services + sub-service cards).
  (function () {
    if (reduce) return;
    if (window.matchMedia('(pointer: coarse)').matches) return;
    document.querySelectorAll('#services .col-md-6, .ld-sub').forEach(function (card) {
      card.addEventListener('mousemove', function (e) {
        var r = card.getBoundingClientRect();
        card.style.setProperty('--sx', ((e.clientX - r.left) / r.width) * 100 + '%');
        card.style.setProperty('--sy', ((e.clientY - r.top) / r.height) * 100 + '%');
      });
    });
  })();

  // On mobile, tapping a dropdown item closes the open menu.
  (function () {
    var toggler = document.querySelector('.navbar-toggler');
    var collapse = document.getElementById('navbarResponsive');
    if (!toggler || !collapse) return;
    collapse.querySelectorAll('.dropdown-item').forEach(function (item) {
      item.addEventListener('click', function () {
        if (window.getComputedStyle(toggler).display !== 'none' && collapse.classList.contains('show')) {
          toggler.click();
        }
      });
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
