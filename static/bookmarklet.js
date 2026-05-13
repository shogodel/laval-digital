(function () {
  // ── Laval Digital Bookmarklet ──────────────────────────────────────────
  // Injects a floating overlay on the current page showing pending actions
  // that need browser-based execution. The user confirms each action and
  // the bookmarklet attempts to execute it via DOM manipulation.
  //
  // Install: drag the bookmarklet from /admin/connector to your bookmarks bar.
  // Click it on any page (Facebook, Google, etc.) to see pending actions.
  // ─────────────────────────────────────────────────────────────────────────

  var BASE = 'https://lavaldigital.ca';
  var CONTAINER_ID = 'ld-bookmarklet-container';
  var existing = document.getElementById(CONTAINER_ID);
  if (existing) { existing.remove(); return; }

  var container = document.createElement('div');
  container.id = CONTAINER_ID;
  container.innerHTML = [
    '<div id="ld-bm-overlay" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.3);z-index:999998;"></div>',
    '<div id="ld-bm-panel" style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:420px;max-height:80vh;background:#fff;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,0.3);z-index:999999;display:flex;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;font-size:14px;color:#1f2937;overflow:hidden;">',
      '<div style="padding:16px 20px;background:#0f2b45;color:#fff;display:flex;align-items:center;justify-content:space-between;">',
        '<strong style="font-size:15px;">&#9889; Laval Digital Actions</strong>',
        '<span id="ld-bm-close" style="cursor:pointer;font-size:20px;line-height:1;">&times;</span>',
      '</div>',
      '<div id="ld-bm-body" style="flex:1;overflow-y:auto;padding:16px 20px;min-height:100px;">',
        '<div style="text-align:center;color:#9ca3af;padding:30px 0;">Loading...</div>',
      '</div>',
      '<div style="padding:12px 20px;border-top:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#9ca3af;">',
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
    fetch(BASE + '/api/actions/pending')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var actions = data.actions || [];
        var countEl = document.getElementById('ld-bm-count');
        countEl.textContent = actions.length + ' pending';
        if (actions.length === 0) {
          body.innerHTML = '<div style="text-align:center;padding:30px 0;color:#9ca3af;">&#10003; No pending actions</div>';
          return;
        }
        body.innerHTML = actions.map(function (a) {
          var preview = (a.content || '').substring(0, 200);
          return [
            '<div style="padding:12px;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:8px;">',
              '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">',
                '<strong style="font-size:13px;">' + escapeHtml(a.agent_name || a.tool_name || 'Action') + '</strong>',
                '<span style="font-size:11px;background:#eff6ff;color:#2563eb;padding:2px 6px;border-radius:4px;">' + escapeHtml(a.provider || 'web') + '</span>',
              '</div>',
              '<div style="font-size:12px;color:#6b7280;margin-bottom:8px;white-space:pre-wrap;word-break:break-word;">' + escapeHtml(preview) + '</div>',
              '<button data-id="' + a.id + '" class="ld-exec-btn" style="background:#D42B2B;color:#fff;border:none;border-radius:6px;padding:6px 16px;font-size:12px;font-weight:600;cursor:pointer;">Execute Now</button>',
              '<span class="ld-status" style="font-size:11px;color:#9ca3af;margin-left:8px;"></span>',
            '</div>',
          ].join('');
        }).join('');

        document.querySelectorAll('.ld-exec-btn').forEach(function (btn) {
          btn.onclick = function () {
            var id = btn.getAttribute('data-id');
            var statusEl = btn.parentElement.querySelector('.ld-status');
            btn.disabled = true;
            btn.textContent = 'Executing...';
            confirmAction(id, function (success, msg) {
              btn.textContent = success ? '\u2713 Done' : '\u2717 Failed';
              statusEl.textContent = msg;
              if (success) { setTimeout(loadActions, 1500); }
            });
          };
        });
      })
      .catch(function () {
        body.innerHTML = '<div style="text-align:center;padding:30px 0;color:#dc2626;">Connection error. Make sure you are logged into Laval Digital.</div>';
      });
  }

  function confirmAction(id, callback) {
    fetch(BASE + '/api/actions/' + id + '/confirm', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        callback(d.success !== false, d.result || d.error || 'Done');
      })
      .catch(function () {
        callback(false, 'Network error');
      });
  }

  function escapeHtml(t) {
    var d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
  }
})();
