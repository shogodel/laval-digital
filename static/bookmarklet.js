(function () {
  var scripts = document.getElementsByTagName('script');
  var src = scripts[scripts.length - 1].src;
  var BASE = src ? src.replace(/\/static\/bookmarklet\.js.*$/, '') : (window.LD_BASE_URL || 'https://lavaldigital.ca');
  var CONTAINER_ID = 'ld-bookmarklet-container';
  var existing = document.getElementById(CONTAINER_ID);
  if (existing) { existing.remove(); return; }

  var container = document.createElement('div');
  container.id = CONTAINER_ID;
  container.innerHTML = [
    '<div id="ld-bm-overlay" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.3);z-index:999998;"></div>',
    '<div id="ld-bm-panel" style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:92%;max-width:440px;max-height:85vh;background:#fff;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,0.3);z-index:999999;display:flex;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;font-size:14px;color:#1f2937;overflow:hidden;">',
      '<div style="padding:14px 18px;background:#0f2b45;color:#fff;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">',
        '<strong style="font-size:15px;">&#9889; Laval Digital Actions</strong>',
        '<span id="ld-bm-close" style="cursor:pointer;font-size:22px;line-height:1;padding:4px;">&times;</span>',
      '</div>',
      '<div id="ld-bm-body" style="flex:1;overflow-y:auto;padding:14px 16px;min-height:80px;-webkit-overflow-scrolling:touch;">',
        '<div style="text-align:center;color:#9ca3af;padding:30px 0;">Loading...</div>',
      '</div>',
      '<div style="padding:10px 16px;border-top:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#9ca3af;flex-shrink:0;">',
        '<span id="ld-bm-count">0 pending</span>',
        '<a href="' + BASE + '/admin/connector" target="_blank" style="color:#2563eb;text-decoration:none;">Settings</a>',
      '</div>',
    '</div>',
  ].join('');
  document.body.appendChild(container);

  document.getElementById('ld-bm-close').onclick = function () { container.remove(); };

  loadActions();

  function loadActions() {
    var body = document.getElementById('ld-bm-body');
    var countEl = document.getElementById('ld-bm-count');
    var all = [];

    // Fetch standard pending actions
    fetch(BASE + '/api/actions/pending')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.actions || []).forEach(function (a) {
          a._type = 'action';
          all.push(a);
        });
        // Also fetch pending SMS
        return fetch(BASE + '/api/actions/sms-pending');
      })
      .then(function (r) { return r.json(); })
      .then(function (smsData) {
        (smsData.messages || []).forEach(function (m) {
          all.push({
            _type: 'sms',
            id: m.timestamp,
            agent_name: 'SMS',
            tool_name: 'send_sms',
            provider: 'sms',
            content: m.content,
            timestamp: m.timestamp,
          });
        });

        countEl.textContent = all.length + ' pending';

        if (all.length === 0) {
          body.innerHTML = '<div style="text-align:center;padding:30px 0;color:#9ca3af;">&#10003; Nothing pending</div>';
          return;
        }

        body.innerHTML = all.map(function (a) {
          var preview = (a.content || '').substring(0, 200);
          var isSms = a._type === 'sms';
          var label = isSms ? 'SMS' : escapeHtml(a.provider || 'web');
          var labelColor = isSms ? 'background:#ecfdf5;color:#059669;' : 'background:#eff6ff;color:#2563eb;';
          var btnHtml = isSms
            ? '<button data-ts="' + escapeHtml(a.timestamp || '') + '" class="ld-copy-btn" style="background:#059669;color:#fff;border:none;border-radius:6px;padding:8px 18px;font-size:14px;font-weight:600;cursor:pointer;width:100%;">📋 Copy & Send</button>'
            : '<button data-id="' + a.id + '" class="ld-exec-btn" style="background:#D42B2B;color:#fff;border:none;border-radius:6px;padding:6px 16px;font-size:12px;font-weight:600;cursor:pointer;">Execute Now</button>';
          return [
            '<div style="padding:12px;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:8px;">',
              '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">',
                '<strong style="font-size:13px;">' + escapeHtml(a.agent_name || a.tool_name || 'Action') + '</strong>',
                '<span style="font-size:11px;' + labelColor + 'padding:2px 8px;border-radius:4px;">' + label + '</span>',
              '</div>',
              '<div style="font-size:13px;color:#374151;margin-bottom:8px;white-space:pre-wrap;word-break:break-word;line-height:1.4;">' + escapeHtml(preview) + '</div>',
              btnHtml,
              '<span class="ld-status" style="font-size:11px;color:#9ca3af;margin-left:6px;"></span>',
            '</div>',
          ].join('');
        }).join('');

        // Wire up Execute buttons
        document.querySelectorAll('.ld-exec-btn').forEach(function (btn) {
          btn.onclick = function () {
            var id = btn.getAttribute('data-id');
            var statusEl = btn.parentElement.querySelector('.ld-status');
            btn.disabled = true; btn.textContent = 'Executing...';
            confirmAction(id, function (ok, msg) {
              btn.textContent = ok ? '\u2713 Done' : '\u2717 Failed';
              statusEl.textContent = msg;
              if (ok) { setTimeout(loadActions, 1500); }
            });
          };
        });

        // Wire up Copy buttons (for SMS on mobile)
        document.querySelectorAll('.ld-copy-btn').forEach(function (btn) {
          btn.onclick = function () {
            var ts = btn.getAttribute('data-ts');
            var parent = btn.parentElement;
            var contentEl = parent.querySelector('div:nth-child(2)');
            var text = contentEl ? contentEl.textContent.trim() : '';
            var statusEl = parent.querySelector('.ld-status');

            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(text).then(function () {
                btn.textContent = '\u2713 Copied! Open SMS app and paste.';
                btn.style.background = '#065f46';
                statusEl.textContent = 'Copied';
                // Mark as sent
                fetch(BASE + '/api/actions/sms-sent', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({timestamp: ts}),
                });
              }).catch(function () {
                fallbackCopy(text, btn, statusEl, ts);
              });
            } else {
              fallbackCopy(text, btn, statusEl, ts);
            }
          };
        });
      })
      .catch(function () {
        body.innerHTML = '<div style="text-align:center;padding:30px 0;color:#dc2626;">Connection error. Make sure you are logged into Laval Digital.</div>';
      });
  }

  function fallbackCopy(text, btn, statusEl, ts) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try {
      document.execCommand('copy');
      btn.textContent = '\u2713 Copied! Open SMS app and paste.';
      btn.style.background = '#065f46';
      statusEl.textContent = 'Copied';
      fetch(BASE + '/api/actions/sms-sent', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({timestamp: ts}),
      });
    } catch (e) {
      btn.textContent = 'Manual: long-press text to copy';
    }
    document.body.removeChild(ta);
  }

  function confirmAction(id, callback) {
    fetch(BASE + '/api/actions/' + id + '/confirm', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) { callback(d.success !== false, d.result || d.error || 'Done'); })
      .catch(function () { callback(false, 'Network error'); });
  }

  function escapeHtml(t) {
    var d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
  }
})();
