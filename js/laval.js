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

  // Contact form: validate locally, then create a Lead in EspoCRM via a
  // Lead Capture entry point (public key by design; creates Leads only).
  // Set LEAD_CAPTURE_URL to the URL shown in EspoCRM under
  // Administration > Lead Capture > <entry> > API URL.
  (function () {
    var form = document.getElementById('contactForm');
    if (!form) return;

    var LEAD_CAPTURE_URL =
      'https://sales.laval.digital/api/v1/LeadCapture/7b53bd21360ef4194a37eeb01919a1a4';

    var isFr = (document.documentElement.lang || '').toLowerCase().indexOf('fr') === 0;
    var copy = isFr
      ? {
          sending: 'Envoi…',
          submit: 'Envoyer le message',
          error:
            'Nous n\'avons pas pu envoyer votre message. Réessayez, ou appelez/textez le (514) 243-1580 — votre texte est conservé.',
        }
      : {
          sending: 'Sending…',
          submit: 'Send Message',
          error:
            'We couldn\'t send your message just now. Please try again, or call/text (514) 243-1580 — your text is kept so you can copy it.',
        };

    var successBox = document.getElementById('submitSuccessMessage');
    var errorBox = document.getElementById('submitErrorMessage');
    var errorText = errorBox && errorBox.querySelector('.text-center');
    var submitBtn = document.getElementById('submitButton');
    var submitting = false;

    function show(box) {
      if (box) box.classList.remove('d-none');
    }
    function hide(box) {
      if (box) box.classList.add('d-none');
    }
    function setError(text) {
      if (errorText) errorText.textContent = text;
      show(errorBox);
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (submitting) return;

      var name = document.getElementById('name');
      var email = document.getElementById('email');
      var phone = document.getElementById('phone');
      var message = document.getElementById('message');
      var ok = true;

      [[name, /.+/], [email, /.+@.+\..+/], [phone, /.+/], [message, /.+/]].forEach(
        function (pair) {
          var field = pair[0],
            rx = pair[1];
          var valid = field && rx.test(field.value.trim());
          field.classList.toggle('is-invalid', !valid);
          if (!valid) ok = false;
        }
      );

      hide(successBox);
      hide(errorBox);
      if (!ok) return;

      var fullName = name.value.trim().replace(/\s+/g, ' ');
      var parts = fullName.split(' ');
      var firstName = parts.length > 1 ? parts.shift() : '';
      var lastName = parts.join(' ') || fullName;

      var payload = {
        firstName: firstName || null,
        lastName: lastName,
        emailAddress: email.value.trim(),
        phoneNumber: phone.value.trim(),
        description: message.value.trim(),
      };

      submitting = true;
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.setAttribute('aria-busy', 'true');
        submitBtn.textContent = copy.sending;
      }

      fetch(LEAD_CAPTURE_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(payload),
      })
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          form.reset();
          show(successBox);
          if (successBox && successBox.scrollIntoView) {
            successBox.scrollIntoView({ block: 'center', behavior: 'smooth' });
          }
        })
        .catch(function () {
          setError(copy.error);
        })
        .finally(function () {
          submitting = false;
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.removeAttribute('aria-busy');
            submitBtn.textContent = copy.submit;
          }
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

  // Contact FAB + choice sheet (SMS-first; no accounts needed).
  (function () {
    var fab = document.getElementById('ldFab');
    var sheet = document.getElementById('ldSheet');
    var backdrop = document.getElementById('ldSheetBackdrop');
    if (!fab || !sheet) return;
    function open() {
      sheet.hidden = false;
      if (backdrop) backdrop.hidden = false;
      fab.setAttribute('aria-expanded', 'true');
      var first = sheet.querySelector('a');
      if (first) first.focus();
    }
    function close(returnFocus) {
      sheet.hidden = true;
      if (backdrop) backdrop.hidden = true;
      fab.setAttribute('aria-expanded', 'false');
      if (returnFocus) fab.focus();
    }
    fab.addEventListener('click', function () {
      if (sheet.hidden) {
        open();
      } else {
        close(false);
      }
    });
    if (backdrop) {
      backdrop.addEventListener('click', function () {
        close(true);
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !sheet.hidden) close(true);
    });
    sheet.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () {
        close(false);
      });
    });
  })();
})();
