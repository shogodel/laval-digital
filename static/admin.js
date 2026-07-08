/* ── Config ── */
var CFG = window.ADMIN_CONFIG || {};
var LOCALE = CFG.locale || 'en';

var S = LOCALE === 'fr' ? {
    /* Toast & status */
    switching: 'Changement...',
    switched: 'Client chang\u00e9!',
    noUserSelected: 'Aucun utilisateur s\u00e9lectionn\u00e9',
    errorPrefix: 'Erreur: ',
    statusProcessing: 'En cours',
    statusPendingApproval: 'Approbation en attente',
    statusPendingConfirmation: 'Confirmation en attente',
    statusIdle: 'Inactif',
    statusDisabled: 'D\u00e9sactiv\u00e9',
    /* Agents */
    noAgents: 'Aucun agent trouv\u00e9.',
    statusLabel: 'Statut',
    modelLabel: 'Mod\u00e8le',
    tasksLabel: 'T\u00e2ches',
    lastLabel: 'Derni\u00e8re',
    chatBtn: '\uD83D\uDCAC Discuter',
    disableBtn: 'D\u00e9sactiver',
    enableBtn: 'Activer',
    agentsOk: ' ok',
    agentsFail: ' \u00e9ch.',
    /* Approvals */
    noApprovals: 'Aucune approbation en attente',
    approveBtn: '\u2713 Approuver',
    rejectBtn: '\u2717 Rejeter',
    confirmRejectBtn: 'Confirmer',
    feedbackPlaceholder: 'Commentaires (optionnel)',
    approvalApproved: 'Approuv\u00e9!',
    approvalRejected: 'Rejet\u00e9!',
    approvalError: 'Erreur: ',
    approvalNetworkError: 'Erreur r\u00e9seau: ',
    approvalUnexpected: 'R\u00e9ponse inattendue du serveur.',
    /* Pending */
    noPendingExecutions: 'Aucune confirmation en attente',
    pendingFailedLoad: '\u00c9chec du chargement',
    confirmExecBtn: 'Confirmer',
    rejectExecBtn: 'Rejeter',
    executionConfirmed: 'Ex\u00e9cution confirm\u00e9e!',
    executionFailed: '\u00c9chec: ',
    executionRejected: 'Ex\u00e9cution rejet\u00e9e.',
    /* Executions */
    noExecutions: 'Aucune ex\u00e9cution',
    draftPreview: 'Aper\u00e7u du brouillon',
    loadFailed: '\u00c9chec du chargement',
    /* Users */
    loadingUsers: 'Chargement des utilisateurs...',
    noUsers: 'Aucun utilisateur trouv\u00e9.',
    emailHeader: 'Courriel',
    nameHeader: 'Nom',
    roleHeader: 'R\u00f4le',
    createdLabel: 'Cr\u00e9\u00e9',
    lastLoginLabel: 'Derni\u00e8re Connexion',
    actionsLabel: 'Actions',
    userRoleClient: 'Client',
    userRoleAffiliate: 'Affili\u00e9',
    deleteUserBtn: 'Supprimer',
    userRequired: 'Le courriel et le mot de passe sont requis.',
    userDeleteConfirm: 'Supprimer cet utilisateur?',
    userDeleted: 'Utilisateur supprim\u00e9.',
    /* Settings */
    saved: 'Sauvegard\u00e9!',
    smtpPasswordPlaceholder: 'Mot de passe d\'application',
    emailTestPrompt: 'Veuillez entrer une adresse courriel de test.',
    sending: 'Envoi...',
    sendTestEmail: '\uD83D\uDCE7 Envoyer un Courriel Test',
    testEmailSuccess: '\u2705 Courriel test envoy\u00e9!',
    testEmailFail: '\u274c \u00c9chec: ',
    apiKeyPrompt: 'Veuillez entrer votre cl\u00e9 API unifi\u00e9e.',
    testingConnection: 'Test de connexion...',
    connectionSuccess: '\u2705 Connexion r\u00e9ussie!',
    connectionFailed: 'Connexion \u00e9chou\u00e9e: ',
    connected: 'Connect\u00e9',
    /* Platform */
    saving: 'Enregistrement...',
    connectSuccess: '\u2713 Connect\u00e9! ',
    connectError: 'Erreur: ',
    connectFail: '\u00c9chec de la connexion. Veuillez r\u00e9essayer.',
    /* MCP */
    noMCPServers: 'Aucun serveur MCP disponible.',
    tools: ' outils',
    mcpLoadFailed: '\u00c9chec du chargement des serveurs MCP.',
    /* Dashboard */
    noErrors: 'Aucune erreur',
    withErrors: ' avec erreurs',
    statSystemOK: '\u2705 OK',
    statSystemDegraded: '\u26a0\ufe0f D\u00e9grad\u00e9',
    /* Install */
    installSafari: 'Sur Safari : appuyez sur l\'ic\u00f4ne Partager en bas, puis "Ajouter \u00e0 l\'\u00e9cran d\'accueil".',
    installBrowser: 'Ouvrez le menu du navigateur et s\u00e9lectionnez "Installer" ou "Ajouter \u00e0 l\'\u00e9cran d\'accueil".',
} : {
    switching: 'Switching...',
    switched: 'Switched!',
    noUserSelected: 'No user selected',
    errorPrefix: 'Error: ',
    statusProcessing: 'Processing',
    statusPendingApproval: 'Pending Approval',
    statusPendingConfirmation: 'Pending Confirmation',
    statusIdle: 'Idle',
    statusDisabled: 'Disabled',
    noAgents: 'No agents found.',
    statusLabel: 'Status',
    modelLabel: 'Model',
    tasksLabel: 'Tasks',
    lastLabel: 'Last',
    chatBtn: '\uD83D\uDCAC Chat',
    disableBtn: 'Disable',
    enableBtn: 'Enable',
    agentsOk: ' ok',
    agentsFail: ' fail',
    noApprovals: 'No pending approvals',
    approveBtn: '\u2713 Approve',
    rejectBtn: '\u2717 Reject',
    confirmRejectBtn: 'Confirm',
    feedbackPlaceholder: 'Feedback (optional)',
    approvalApproved: 'Approval approved!',
    approvalRejected: 'Approval rejected!',
    approvalError: 'Error: ',
    approvalNetworkError: 'Network error: ',
    approvalUnexpected: 'Unexpected response from server.',
    noPendingExecutions: 'No pending confirmations',
    pendingFailedLoad: 'Failed to load',
    confirmExecBtn: 'Confirm',
    rejectExecBtn: 'Reject',
    executionConfirmed: 'Execution confirmed!',
    executionFailed: 'Failed: ',
    executionRejected: 'Execution rejected.',
    noExecutions: 'No executions yet',
    draftPreview: 'Draft preview',
    loadFailed: 'Failed to load',
    loadingUsers: 'Loading users...',
    noUsers: 'No users found for this tenant.',
    emailHeader: 'Email',
    nameHeader: 'Name',
    roleHeader: 'Role',
    createdLabel: 'Created',
    lastLoginLabel: 'Last Login',
    actionsLabel: 'Actions',
    userRoleClient: 'client',
    userRoleAffiliate: 'affiliate',
    deleteUserBtn: 'Delete',
    userRequired: 'Email and password are required.',
    userDeleteConfirm: 'Delete this user?',
    userDeleted: 'User deleted.',
    saved: 'Saved!',
    smtpPasswordPlaceholder: 'App password',
    emailTestPrompt: 'Please enter a test email address.',
    sending: 'Sending...',
    sendTestEmail: '\uD83D\uDCE7 Send Test Email',
    testEmailSuccess: '\u2705 Test email sent! Check your inbox.',
    testEmailFail: '\u274c Failed: ',
    apiKeyPrompt: 'Please enter your unified API key.',
    testingConnection: 'Testing connection...',
    connectionSuccess: '\u2705 Connection successful!',
    connectionFailed: 'Connection failed: ',
    connected: 'Connected',
    saving: 'Saving...',
    connectSuccess: '\u2713 Connected! ' + (CFG.agentName || 'AI Assistant') + ' can now publish to your ',
    connectError: 'Error: ',
    connectFail: 'Connection failed. Please try again.',
    noMCPServers: 'No MCP servers available.',
    tools: ' tools',
    mcpLoadFailed: 'Failed to load MCP servers.',
    noErrors: 'No errors',
    withErrors: ' with errors',
    statSystemOK: '\u2705 OK',
    statSystemDegraded: '\u26a0\ufe0f Degraded',
    installSafari: 'On Safari: tap the Share icon at the bottom, then "Add to Home Screen".',
    installBrowser: 'Open the browser menu and select "Install" or "Add to Home Screen".',
};

/* ── AGENT_META (locale-aware) ── */
var AGENT_META = LOCALE === 'fr' ? {
    local_seo: { name: 'SEO Local', desc: 'Optimisation du profil Google Business, citations locales, contenu de mots-cl\u00e9s locaux, gestion des avis' },
    social_media: { name: 'M\u00e9dias Sociaux', desc: 'Publications sur les r\u00e9seaux sociaux, cr\u00e9ation de contenu, calendriers de contenu, strat\u00e9gies d\'engagement' },
    lead_conversion: { name: 'Conversion de Prospects', desc: 'S\u00e9quences de suivi des prospects, int\u00e9gration CRM, optimisation des conversions, campagnes courriel' },
    paid_ads: { name: 'Annonces Payantes', desc: 'Campagnes Google & Meta, cr\u00e9ation de contenu publicitaire, strat\u00e9gie de mots-cl\u00e9s, allocation budg\u00e9taire, tests A/B, ciblage d\'audience' },
    growth_hacker: { name: 'Growth Hacker', desc: 'Audits de croissance, boucles virales, optimisation du taux de conversion, strat\u00e9gies de partenariat, exp\u00e9riences bas\u00e9es sur les donn\u00e9es' },
    reputation: { name: 'R\u00e9putation', desc: 'Surveillance des avis en ligne, g\u00e9n\u00e9ration de r\u00e9ponses aux avis, campagnes de sollicitation d\'avis, audits de r\u00e9putation, gestion de crise' },
    email_marketing: { name: 'Marketing Courriel', desc: 'Campagnes infolettres, courriels promotionnels, s\u00e9quences de nurturing, campagnes de r\u00e9activation, suivis post-service' },
    tiktok: { name: 'TikTok', desc: 'Contenu vid\u00e9o court pour TikTok, Instagram Reels, YouTube Shorts, calendriers de contenu, scripts vid\u00e9o, adaptation aux tendances' },
    outreach: { name: 'Prospection', desc: 'Courriels de prospection, recherche de prospects, s\u00e9quences de campagnes, automatisation de suivi, prospection personnalis\u00e9e \u00e0 grande \u00e9chelle' },
    backlinks: { name: 'Backlinks', desc: 'Cr\u00e9ation de liens, prospection d\'articles invit\u00e9s, cr\u00e9ation de citations, analyse des \u00e9carts de backlinks, r\u00e9cup\u00e9ration de liens bris\u00e9s, soumissions d\'annuaires' },
    content_strategy: { name: 'Strat\u00e9gie de Contenu', desc: 'Calendriers \u00e9ditoriaux, r\u00e9utilisation multi-canal, briefs de contenu, clusters th\u00e9matiques, planification saisonni\u00e8re' },
    technical_seo: { name: 'SEO Technique', desc: 'Balises schema, optimisation de vitesse, audits de crawl, sitemaps XML, Core Web Vitals, optimisation mobile' },
    reporting: { name: 'Analytiques & Rapports', desc: 'R\u00e9sum\u00e9s de performance multi-canaux, analyse de tendances, calculs ROI, briefs ex\u00e9cutifs, rapports mensuels' },
    cro: { name: 'CRO & Pages d\'Atterrissage', desc: 'Optimisation du taux de conversion, analyse de tests A/B, optimisation d\'entonnoir, strat\u00e9gie CTA' },
    video: { name: 'Production Vid\u00e9o', desc: 'Scripts YouTube, vid\u00e9os explicatives, scripts publicitaires, SEO vid\u00e9o, planification de s\u00e9ries' },
    sms_marketing: { name: 'Marketing SMS', desc: 'Planification de campagnes SMS, conception de s\u00e9quences, conformit\u00e9 CASL, r\u00e9daction concise, strat\u00e9gie de timing' },
} : {
    local_seo: { name: 'Local SEO', desc: 'Google Business Profile optimization, local citations, local keyword content, review management' },
    social_media: { name: 'Social Media', desc: 'Social media posts, content creation, content calendars, engagement strategies' },
    lead_conversion: { name: 'Lead Conversion', desc: 'Lead follow-up sequences, CRM integration, conversion optimization, email campaigns' },
    paid_ads: { name: 'Paid Ads', desc: 'Google & Meta campaigns, ad content creation, keyword strategy, budget allocation, A/B testing, audience targeting' },
    growth_hacker: { name: 'Growth Hacker', desc: 'Growth audits, viral loops, conversion rate optimization, partnership strategies, data-driven experiments' },
    reputation: { name: 'Reputation', desc: 'Online review monitoring, review response generation, review solicitation campaigns, reputation audits, crisis management' },
    email_marketing: { name: 'Email Marketing', desc: 'Newsletter campaigns, promotional emails, nurturing sequences, reactivation campaigns, post-service follow-ups' },
    tiktok: { name: 'TikTok', desc: 'Short-form video content for TikTok, Instagram Reels, YouTube Shorts, content calendars, video scripts, trend adaptation' },
    outreach: { name: 'Outreach', desc: 'Outreach emails, prospect research, campaign sequences, follow-up automation, personalized outreach at scale' },
    backlinks: { name: 'Backlinks', desc: 'Link building, guest post prospecting, citation building, backlink gap analysis, broken link recovery, directory submissions' },
    content_strategy: { name: 'Content Strategy', desc: 'Editorial calendars, multi-channel repurposing, content briefs, topic clusters, seasonal planning' },
    technical_seo: { name: 'Technical SEO', desc: 'Schema markup, speed optimization, crawl audits, XML sitemaps, Core Web Vitals, mobile optimization' },
    reporting: { name: 'Analytics & Reporting', desc: 'Multi-channel performance summaries, trend analysis, ROI calculations, executive briefs, monthly reports' },
    cro: { name: 'CRO & Landing Pages', desc: 'Conversion rate optimization, A/B test analysis, funnel optimization, CTA strategy' },
    video: { name: 'Video Production', desc: 'YouTube scripts, explainer videos, ad scripts, video SEO, series planning' },
    sms_marketing: { name: 'SMS Marketing', desc: 'SMS campaign planning, sequence design, CASL compliance, concise copywriting, timing strategy' },
};

var AGENT_PERSONALITIES = {};
var togglePromise = Promise.resolve();
var deferredPrompt = null;

/* ── Toast ── */
function toast(msg, type) {
    var el = document.getElementById('toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'toast';
        el.style.cssText = 'display:none;position:fixed;bottom:24px;right:24px;z-index:9999;background:#1f2937;color:#fff;padding:12px 20px;border-radius:10px;font-size:0.85rem;font-weight:500;box-shadow:0 4px 20px rgba(0,0,0,0.2);max-width:360px;transition:opacity 0.3s;';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.background = type === 'error' ? '#dc2626' : type === 'success' ? '#059669' : '#1f2937';
    el.style.display = 'block';
    el.style.opacity = '1';
    clearTimeout(el._hide);
    el._hide = setTimeout(function() {
        el.style.opacity = '0';
        setTimeout(function() { el.style.display = 'none'; }, 300);
    }, 4000);
}

/* ── CSRF patch ── */
(function() {
    var token = document.querySelector('meta[name="csrf-token"]');
    if (!token) return;
    var origFetch = window.fetch;
    window.fetch = function(url, opts) {
        opts = opts || {};
        if (!opts.method || opts.method === 'GET' || opts.method === 'HEAD' || opts.method === 'OPTIONS')
            return origFetch.call(this, url, opts);
        opts.headers = opts.headers || {};
        if (opts.headers instanceof Headers) {
            if (!opts.headers.has('X-CSRFToken'))
                opts.headers.append('X-CSRFToken', token.content);
        } else {
            opts.headers['X-CSRFToken'] = opts.headers['X-CSRFToken'] || token.content;
        }
        return origFetch.call(this, url, opts);
    };
})();

/* ── Tab navigation ── */
function switchTab(tab) {
    document.querySelectorAll('.sidebar-nav a').forEach(function(a) {
        a.classList.remove('active');
        a.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.tab-content').forEach(function(t) {
        t.classList.remove('active');
    });
    var link = document.querySelector('.sidebar-nav a[data-tab="' + tab + '"]');
    if (link) {
        link.classList.add('active');
        link.setAttribute('aria-selected', 'true');
        var titleEl = document.getElementById('page-title');
        if (titleEl) titleEl.textContent = link.textContent.trim();
    }
    var tabEl = document.getElementById('tab-' + tab);
    if (tabEl) tabEl.classList.add('active');
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('overlay').classList.toggle('show');
}

/* ── Tenant switching ── */
function switchTenant(tenantId) {
    var sel = document.getElementById('tenant-select');
    var el = document.getElementById('tenant-switch-result');
    if (!sel || !el) return;
    sel.disabled = true;
    el.textContent = S.switching;
    fetch('/api/tenants/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        el.textContent = data.message || S.switched;
        var labelEl = document.getElementById('active-tenant-label');
        if (labelEl) labelEl.textContent = data.active_tenant || S.noUserSelected;
        var dot = document.querySelector('.tenant-pill .dot');
        if (dot) dot.className = data.active_tenant ? 'dot active' : 'dot inactive';
        refreshAll();
    })
    .catch(function(err) { el.textContent = S.errorPrefix + err.message; })
    .finally(function() { sel.disabled = false; });
}

function refreshAll() {
    loadAgents();
    loadApprovals();
    loadPendingExecutions();
    loadExecutions();
    updateDashboard();
    loadUsers();
    if (typeof loadAnalytics === 'function') loadAnalytics();
    if (typeof loadManagedClients === 'function') loadManagedClients();
}

/* ── Dashboard ── */
function updateDashboard() {
    var ids = ['stat-agents', 'stat-active', 'stat-processing', 'stat-pending', 'stat-executions', 'stat-success-rate', 'stat-failed', 'stat-health'];
    ids.forEach(function(id) {
        var el = document.getElementById(id);
        if (el && !el.dataset.loaded) el.textContent = '...';
    });
    Promise.allSettled([
        fetch('/api/agents').then(function(r) { return r.json(); }).then(function(data) {
            var agents = data.agents || [];
            var el = document.getElementById('stat-agents');
            if (el) { el.textContent = agents.length; el.dataset.loaded = '1'; }
            el = document.getElementById('stat-active');
            if (el) { el.textContent = agents.filter(function(a) { return a.enabled; }).length; el.dataset.loaded = '1'; }
            var processing = agents.filter(function(a) { return a.status === 'processing'; }).length;
            el = document.getElementById('stat-processing');
            if (el) { el.textContent = processing; el.dataset.loaded = '1'; }
            var healthEl = document.getElementById('dashboard-agent-health');
            if (healthEl) {
                var idle = agents.filter(function(a) { return a.enabled && a.status === 'idle'; }).length;
                var err = agents.filter(function(a) { return a.status === 'error' || a.failure_count > 0; }).length;
                healthEl.innerHTML = '<span class="badge badge-idle" style="padding:6px 14px;">\u2705 ' + idle + ' ' + S.statusIdle.toLowerCase() + '</span>'
                    + '<span class="badge" style="padding:6px 14px;background:#dbeafe;color:#1e40af;">\u2699\ufe0f ' + processing + ' ' + S.statusProcessing.toLowerCase() + '</span>'
                    + '<span class="badge" style="padding:6px 14px;background:'
                    + (err ? '#fef2f2;color:#991b1b' : '#f0fdf4;color:#166534') + ';">'
                    + (err ? '\u26a0\ufe0f ' + err + S.withErrors : '\u2705 ' + S.noErrors) + '</span>';
            }
        }),
        fetch('/api/approvals').then(function(r) { return r.json(); }).then(function(data) {
            var el = document.getElementById('stat-pending');
            if (el) { el.textContent = (data.approvals || []).length; el.dataset.loaded = '1'; }
        }),
        fetch('/api/executions').then(function(r) { return r.json(); }).then(function(data) {
            var execs = data.executions || [];
            ids.forEach(function(id) {
                var el = document.getElementById(id);
                if (el && ['stat-executions', 'stat-success-rate', 'stat-failed'].indexOf(id) >= 0) el.dataset.loaded = '1';
            });
            var el = document.getElementById('stat-executions');
            if (el) el.textContent = execs.length;
            var successes = execs.filter(function(e) { return e.success; }).length;
            var failures = execs.filter(function(e) { return !e.success; }).length;
            el = document.getElementById('stat-success-rate');
            if (el) el.textContent = execs.length ? Math.round(successes / execs.length * 100) + '%' : '\u2014';
            el = document.getElementById('stat-failed');
            if (el) el.textContent = failures;
            var alertEl = document.getElementById('dashboard-alert');
            if (alertEl) {
                var rate = execs.length ? successes / execs.length : 1;
                if (rate < 0.8 && execs.length > 5) {
                    alertEl.style.display = 'block';
                    alertEl.style.background = '#fef2f2';
                    alertEl.style.color = '#991b1b';
                    alertEl.style.border = '1px solid #fecaca';
                    alertEl.textContent = '\u26a0\ufe0f Execution success rate is ' + Math.round(rate * 100) + '% \u2014 below the 80% threshold. Check the Analytics tab for details.';
                } else {
                    alertEl.style.display = 'none';
                }
            }
        }),
        fetch('/api/health').then(function(r) { return r.json(); }).then(function(data) {
            var el = document.getElementById('stat-health');
            if (el) { el.textContent = data.status === 'ok' ? S.statSystemOK : S.statSystemDegraded; el.dataset.loaded = '1'; }
        }),
    ]);
}

/* ── Agents ── */
function loadPersonalities() {
    return fetch('/api/personalities')
        .then(function(r) { return r.json(); })
        .then(function(data) { AGENT_PERSONALITIES = data.personalities || {}; })
        .catch(function(e) { console.error(e); });
}

function loadAgents() {
    return fetch('/api/agents')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var agents = data.agents || [];
            var html = agents.map(function(a) {
                var meta = AGENT_META[a.agent_id] || { name: a.agent_id.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }), desc: '' };
                var p = AGENT_PERSONALITIES[a.agent_id] || {};
                var emoji = p.emoji || '\uD83E\uDD16';
                var color = p.color || '#6b7280';
                var status = a.enabled ? a.status : 'disabled';
                var statusMap = {};
                statusMap['processing'] = S.statusProcessing;
                statusMap['pending_approval'] = S.statusPendingApproval;
                statusMap['pending_confirmation'] = S.statusPendingConfirmation;
                statusMap['idle'] = S.statusIdle;
                statusMap['disabled'] = S.statusDisabled;
                var lastInvoked = a.last_invoked ? new Date(a.last_invoked).toLocaleString() : '--';
                var aid = escapeHtml(a.agent_id);
                return '<div class="agent-card ' + (a.enabled ? 'enabled' : 'disabled') + '" data-agent-id="' + aid + '">'
                    + '<div class="agent-name"><span style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:' + color + '20;font-size:0.8rem;margin-right:6px;">' + emoji + '</span>' + escapeHtml(meta.name) + '</div>'
                    + '<div class="agent-desc">' + escapeHtml(meta.desc) + '</div>'
                    + '<div class="row"><span class="label">' + S.statusLabel + '</span><span class="badge badge-' + status + '">' + (statusMap[status] || S.statusIdle) + '</span></div>'
                    + '<div class="row"><span class="label">' + S.modelLabel + '</span><span class="value">' + escapeHtml(a.model) + '</span></div>'
                    + '<div class="row"><span class="label">' + S.tasksLabel + '</span><span class="value">' + a.task_count + ' (' + a.success_count + S.agentsOk + ' / ' + a.failure_count + S.agentsFail + ')</span></div>'
                    + '<div class="row"><span class="label">' + S.lastLabel + '</span><span class="value">' + lastInvoked + '</span></div>'
                    + '<div class="draft-preview">' + escapeHtml(a.last_draft_preview || '\u2014') + '</div>'
                    + '<div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;">'
                    + '<button class="btn btn-gray btn-xs chat-agent-btn" data-agent-id="' + aid + '">' + S.chatBtn + '</button>'
                    + '<button class="btn btn-' + (a.enabled ? 'gray' : 'green') + ' btn-xs toggle-agent-btn" data-agent-id="' + aid + '">' + (a.enabled ? S.disableBtn : S.enableBtn) + '</button>'
                    + '</div></div>';
            }).join('');
            var listEl = document.getElementById('agent-list');
            if (listEl) listEl.innerHTML = html || '<p class="empty">' + S.noAgents + '</p>';
            updateDashboard();
        });
}

function toggleAgent(agentId) {
    togglePromise = togglePromise.then(function() {
        var card = document.querySelector('[data-agent-id="' + agentId + '"]');
        var btn = card ? card.querySelector('.toggle-agent-btn, .toggle-btn') : null;
        if (btn) btn.disabled = true;
        return fetch('/api/agents/' + agentId + '/toggle', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function() { return loadAgents(); });
    });
}

/* ── Tasks ── */
function loadApprovals() {
    fetch('/api/approvals')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var approvals = data.approvals || [];
            var list = document.getElementById('approvals-list');
            if (!list) return;
            if (!approvals.length) {
                list.innerHTML = '<p class="empty">' + S.noApprovals + '</p>';
                updateDashboard();
                return;
            }
            list.innerHTML = approvals.map(function(a) {
                var tid = escapeHtml(a.thread_id);
                return '<div class="approval-card" data-thread-id="' + tid + '">'
                    + '<h3>' + S.approvalAgentPrefix + ' ' + escapeHtml(a.agent) + '</h3>'
                    + '<p><strong>' + S.approvalTaskLabel + '</strong> ' + escapeHtml(a.task) + '</p>'
                    + '<p><strong>' + S.approvalDraftLabel + '</strong></p>'
                    + '<pre>' + escapeHtml(a.draft) + '</pre>'
                    + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">'
                    + '<button class="btn btn-green btn-sm approve-btn" data-thread-id="' + tid + '" data-approved="true">' + S.approveBtn + '</button>'
                    + '<button class="btn btn-gray btn-sm reject-show-btn" data-thread-id="' + tid + '">' + S.rejectBtn + '</button>'
                    + '</div>'
                    + '<div class="reject-form" data-thread-id="' + tid + '" style="display:none;margin-top:8px;">'
                    + '<div style="display:flex;gap:8px;">'
                    + '<input type="text" class="reject-feedback" placeholder="' + S.feedbackPlaceholder + '" style="flex:1;">'
                    + '<button class="btn btn-red btn-sm reject-confirm-btn" data-thread-id="' + tid + '">' + S.confirmRejectBtn + '</button>'
                    + '</div></div></div>';
            }).join('');
            updateDashboard();
        });
}

/* Note: localizable strings used above */
S.approvalAgentPrefix = LOCALE === 'fr' ? 'Agent:' : 'Agent:';
S.approvalTaskLabel = LOCALE === 'fr' ? 'T\u00e2che:' : 'Task:';
S.approvalDraftLabel = LOCALE === 'fr' ? 'Brouillon:' : 'Draft:';

function showRejectForm(threadId) {
    var form = document.querySelector('.reject-form[data-thread-id="' + threadId + '"]');
    if (form) form.style.display = 'block';
}

function respondApproval(threadId, approved, btn) {
    btn.disabled = true;
    var card = document.querySelector('.approval-card[data-thread-id="' + threadId + '"]');
    var feedback = '';
    if (card) {
        var fb = card.querySelector('.reject-feedback');
        if (fb) feedback = fb.value;
    }
    fetch('/api/approvals/' + threadId + '/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: approved, feedback: feedback })
    })
    .then(function(r) {
        if (!r.ok) throw new Error('Server returned ' + r.status);
        return r.json();
    })
    .then(function(data) {
        if (data.status === 'completed') {
            toast(approved ? S.approvalApproved : S.approvalRejected, 'success');
            loadApprovals();
            loadAgents();
            loadPendingExecutions();
            updateDashboard();
        } else if (data.error) {
            toast(S.approvalError + data.error, 'error');
        } else {
            toast(S.approvalUnexpected, 'error');
        }
    })
    .catch(function(err) { toast(S.approvalNetworkError + err.message, 'error'); })
    .finally(function() { btn.disabled = false; });
}

/* ── Pending Confirmations ── */
function loadPendingExecutions() {
    fetch('/api/executioner/pending')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var list = document.getElementById('pending-executions-list');
            if (!list) return;
            if (!data.pending || !data.pending.length) {
                list.innerHTML = '<p class="empty">' + S.noPendingExecutions + '</p>';
                return;
            }
            list.innerHTML = data.pending.map(function(p) {
                var eid = escapeHtml(p.execution_id);
                return '<div class="approval-card" style="background:var(--blue-bg);border-color:#bfdbfe;" data-exec-id="' + eid + '">'
                    + '<p><strong>' + (LOCALE === 'fr' ? 'Agent:' : 'Agent:') + '</strong> ' + escapeHtml(p.agent_name) + ' &middot; <strong>' + (LOCALE === 'fr' ? 'Outil:' : 'Tool:') + '</strong> ' + escapeHtml(p.tool_name) + '</p>'
                    + '<p><small>' + new Date(p.created_at).toLocaleString() + '</small></p>'
                    + '<pre style="font-size:0.8em;">' + escapeHtml(p.draft_preview) + '</pre>'
                    + '<div style="display:flex;gap:8px;">'
                    + '<button class="btn btn-green btn-sm confirm-exec-btn" data-exec-id="' + eid + '">' + S.confirmExecBtn + '</button>'
                    + '<button class="btn btn-red btn-sm reject-exec-btn" data-exec-id="' + eid + '">' + S.rejectExecBtn + '</button>'
                    + '</div></div>';
            }).join('');
        })
        .catch(function() {
            var list = document.getElementById('pending-executions-list');
            if (list) list.innerHTML = '<p class="empty">' + S.pendingFailedLoad + '</p>';
        });
}

function confirmPending(executionId, btn) {
    btn.disabled = true;
    fetch('/api/executioner/confirm/' + executionId, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) { loadPendingExecutions(); loadAgents(); toast(S.executionConfirmed, 'success'); }
            else toast(S.executionFailed + (data.error || 'unknown'), 'error');
        })
        .catch(function(err) { toast(S.errorPrefix + err.message, 'error'); })
        .finally(function() { btn.disabled = false; });
}

function rejectPending(executionId, btn) {
    btn.disabled = true;
    fetch('/api/executioner/reject/' + executionId, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function() { loadPendingExecutions(); toast(S.executionRejected, 'success'); })
        .catch(function(err) { toast(S.errorPrefix + err.message, 'error'); })
        .finally(function() { btn.disabled = false; });
}

/* ── Execution Activity ── */
function loadExecutions() {
    fetch('/api/executions')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var list = document.getElementById('execution-list');
            if (!list) return;
            if (!data.executions || !data.executions.length) {
                list.innerHTML = '<p class="empty">' + S.noExecutions + '</p>';
                return;
            }
            list.innerHTML = data.executions.slice(0, 20).map(function(e) {
                return '<div class="execution-card ' + (e.success ? 'success' : 'fail') + '">'
                    + '<strong>' + escapeHtml(e.agent_name) + '</strong> &middot; ' + escapeHtml(e.tool_name) + ' &middot; <small>' + new Date(e.timestamp).toLocaleString() + '</small>'
                    + (e.error ? ' &middot; <span style="color:var(--red);">' + escapeHtml(e.error) + '</span>' : '')
                    + '<details style="margin-top:4px;"><summary style="cursor:pointer;font-size:0.8rem;color:var(--gray-500);">' + S.draftPreview + '</summary><pre style="font-size:0.75rem;margin-top:4px;white-space:pre-wrap;">' + escapeHtml(e.draft_preview) + '</pre></details>'
                    + '</div>';
            }).join('');
            updateDashboard();
        })
        .catch(function() {
            var list = document.getElementById('execution-list');
            if (list) list.innerHTML = '<p class="empty">' + S.loadFailed + '</p>';
        });
}

/* ── User Management ── */
function loadUsers() {
    var roleFilter = document.getElementById('user-role-filter');
    var roleVal = roleFilter ? roleFilter.value : '';
    var list = document.getElementById('users-list');
    if (!list) return;
    list.innerHTML = '<p class="empty">' + S.loadingUsers + '</p>';
    fetch('/api/users?role=' + encodeURIComponent(roleVal))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { list.innerHTML = '<p class="empty">' + escapeHtml(data.error) + '</p>'; return; }
            var users = data.users || [];
            if (!users.length) { list.innerHTML = '<p class="empty">' + S.noUsers + '</p>'; return; }
            list.innerHTML = '<div style="overflow-x:auto;"><table><thead><tr>'
                + '<th>' + S.emailHeader + '</th><th>' + S.nameHeader + '</th><th>' + S.roleHeader + '</th>'
                + '<th>' + S.createdLabel + '</th><th>' + S.lastLoginLabel + '</th><th>' + S.actionsLabel + '</th>'
                + '</tr></thead><tbody>'
                + users.map(function(u) {
                    return '<tr>'
                        + '<td>' + escapeHtml(u.email) + '</td>'
                        + '<td>' + escapeHtml(u.display_name || '\u2014') + '</td>'
                        + '<td><span class="badge badge-' + (u.role === 'client' ? 'blue' : 'amber') + '">' + escapeHtml(u.role === 'client' ? S.userRoleClient : S.userRoleAffiliate) + '</span></td>'
                        + '<td>' + escapeHtml(u.created_at ? u.created_at.slice(0, 10) : '\u2014') + '</td>'
                        + '<td>' + escapeHtml(u.last_login ? u.last_login.slice(0, 10) : '\u2014') + '</td>'
                        + '<td><button class="btn btn-gray btn-xs delete-user-btn" data-user-id="' + escapeHtml(u.id) + '">' + S.deleteUserBtn + '</button></td>'
                        + '</tr>';
                }).join('')
                + '</tbody></table></div>';
        })
        .catch(function() {
            var list = document.getElementById('users-list');
            if (list) list.innerHTML = '<p class="empty">' + S.loadFailed + '</p>';
        });
}

function showAddUser() {
    var modal = document.getElementById('user-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    var errorEl = document.getElementById('add-user-error');
    if (errorEl) errorEl.textContent = '';
    ['new-user-email', 'new-user-name', 'new-user-password'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.value = '';
    });
    var firstInput = document.getElementById('new-user-email');
    if (firstInput) firstInput.focus();
}

function closeAddUser() {
    var modal = document.getElementById('user-modal');
    if (modal) modal.style.display = 'none';
}

function trapModalFocus(e) {
    var modal = document.getElementById('user-modal');
    if (!modal || modal.style.display === 'none') return;
    var focusable = modal.querySelectorAll('input, select, textarea, button, [tabindex]:not([tabindex="-1"])');
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (e.shiftKey && e.target === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && e.target === last) { e.preventDefault(); first.focus(); }
}

function addUser() {
    var btn = document.getElementById('create-user-btn') || document.getElementById('add-user-btn');
    if (!btn) return;
    btn.disabled = true;
    var email = document.getElementById('new-user-email');
    var name = document.getElementById('new-user-name');
    var password = document.getElementById('new-user-password');
    var role = document.getElementById('new-user-role');
    var errorEl = document.getElementById('add-user-error');
    if (!email || !password || !role) { btn.disabled = false; return; }
    var emailVal = email.value.trim();
    var nameVal = name ? name.value.trim() : '';
    var passwordVal = password.value;
    var roleVal = role.value;
    if (!emailVal || !passwordVal) {
        if (errorEl) errorEl.textContent = S.userRequired;
        btn.disabled = false;
        return;
    }
    fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: emailVal, display_name: nameVal, password: passwordVal, role: roleVal })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) { if (errorEl) errorEl.textContent = data.error; return; }
        closeAddUser();
        loadUsers();
    })
    .catch(function(err) { if (errorEl) errorEl.textContent = S.errorPrefix + err.message; })
    .finally(function() { btn.disabled = false; });
}

function deleteUser(userId, btn) {
    if (!confirm(S.userDeleteConfirm)) return;
    btn.disabled = true;
    fetch('/api/users/' + userId, { method: 'DELETE' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { toast(data.error, 'error'); return; }
            toast(S.userDeleted, 'success');
            loadUsers();
        })
        .catch(function(err) { toast(S.errorPrefix + err.message, 'error'); })
        .finally(function() { btn.disabled = false; });
}

/* ── Execution Settings ── */
function loadExecutionerSettings() {
    fetch('/api/executioner/settings')
        .then(function(r) { return r.json(); })
        .then(function(s) {
            var el;
            el = document.getElementById('smtp-host'); if (el) el.value = s.smtp_host || '';
            el = document.getElementById('smtp-port'); if (el) el.value = s.smtp_port || 587;
            el = document.getElementById('smtp-username'); if (el) el.value = s.smtp_username || '';
            el = document.getElementById('smtp-password'); if (el) { el.value = ''; el.placeholder = s.smtp_password ? '\xb7\xb7\xb7\xb7\xb7\xb7\xb7\xb7' : S.smtpPasswordPlaceholder; }
            el = document.getElementById('smtp-from'); if (el) el.value = s.smtp_from_email || '';
            el = document.getElementById('smtp-tls'); if (el) el.checked = s.smtp_use_tls !== false;
            el = document.getElementById('social-api-provider'); if (el) el.value = s.social_api_provider || 'socialapi';
            el = document.getElementById('unified-social-api-key'); if (el) el.value = s.social_api_key || '';
        })
        .catch(function(e) { console.error(e); });
}

function saveExecutionerSettings() {
    var btn = document.getElementById('save-settings-btn');
    if (!btn) return;
    btn.disabled = true;
    var pw = document.getElementById('smtp-password');
    var settings = {
        smtp_host: (document.getElementById('smtp-host') || {}).value || '',
        smtp_port: parseInt((document.getElementById('smtp-port') || {}).value) || 587,
        smtp_username: (document.getElementById('smtp-username') || {}).value || '',
        smtp_from_email: (document.getElementById('smtp-from') || {}).value || '',
        smtp_use_tls: (document.getElementById('smtp-tls') || {}).checked !== false,
        social_api_provider: (document.getElementById('social-api-provider') || {}).value || 'socialapi',
        unified_social_api_key: (document.getElementById('unified-social-api-key') || {}).value || '',
    };
    if (pw && pw.value) settings.smtp_password = pw.value;
    fetch('/api/executioner/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
    .then(function(r) { return r.json(); })
    .then(function() {
        var resultEl = document.getElementById('executioner-settings-result');
        if (resultEl) {
            resultEl.innerHTML = '<span style="color:var(--green);">' + S.saved + '</span>';
            setTimeout(function() { if (resultEl) resultEl.textContent = ''; }, 3000);
        }
    })
    .catch(function(err) {
        var resultEl = document.getElementById('executioner-settings-result');
        if (resultEl) {
            resultEl.innerHTML = '';
            var span = document.createElement('span');
            span.style.color = 'var(--red)';
            span.textContent = S.errorPrefix + err.message;
            resultEl.appendChild(span);
        }
    })
    .finally(function() { btn.disabled = false; });
}

function testSmtp(event) {
    var testEmail = document.getElementById('smtp-test-email');
    if (!testEmail || !testEmail.value) { alert(S.emailTestPrompt); return; }
    var btn = event.target;
    btn.disabled = true;
    btn.textContent = S.sending;
    var host = (document.getElementById('smtp-host') || {}).value || '';
    var port = parseInt((document.getElementById('smtp-port') || {}).value) || 587;
    var user = (document.getElementById('smtp-username') || {}).value || '';
    var pw = (document.getElementById('smtp-password') || {}).value || '';
    var from = (document.getElementById('smtp-from') || {}).value || user;
    var tls = (document.getElementById('smtp-tls') || {}).checked !== false;
    fetch('/api/executioner/test-smtp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to_email: testEmail.value, smtp_host: host, smtp_port: port, smtp_username: user, smtp_password: pw, smtp_from_email: from, smtp_use_tls: tls })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var msg = data.success ? S.testEmailSuccess : S.testEmailFail + escapeHtml(data.error || '');
        var resultEl = document.getElementById('executioner-settings-result');
        if (resultEl) resultEl.innerHTML = '<span style="color:' + (data.success ? 'var(--green)' : 'var(--red)') + ';">' + msg + '</span>';
    })
    .catch(function(err) {
        var resultEl = document.getElementById('executioner-settings-result');
        if (resultEl) resultEl.innerHTML = '<span style="color:var(--red);">' + S.errorPrefix + escapeHtml(err.message) + '</span>';
    })
    .finally(function() {
        btn.disabled = false;
        btn.textContent = S.sendTestEmail;
    });
}

function validateSocialApiKey() {
    var btn = document.getElementById('test-social-key-btn') || document.getElementById('validate-social-btn');
    if (!btn) return;
    btn.disabled = true;
    var provider = (document.getElementById('social-api-provider') || {}).value || '';
    var apiKey = (document.getElementById('unified-social-api-key') || {}).value || '';
    if (!apiKey) { btn.disabled = false; alert(S.apiKeyPrompt); return; }
    var resultDiv = document.getElementById('social-key-validation-result');
    if (!resultDiv) { btn.disabled = false; return; }
    resultDiv.innerHTML = '<span style="color:var(--blue);">' + S.testingConnection + '</span>';
    fetch('/api/executioner/validate-social-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: provider, api_key: apiKey })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            resultDiv.innerHTML = '<span style="color:var(--green);">' + S.connectionSuccess + '</span>';
            var accountsHtml = (data.accounts || []).map(function(acc) {
                return '<div class="agent-card enabled" style="padding:10px;margin:4px 0;">'
                    + '<span style="font-weight:700;">' + escapeHtml(acc.platform || acc.name) + '</span> \u2014 ' + escapeHtml(acc.account_name)
                    + ' <span class="badge badge-idle">' + S.connected + '</span></div>';
            }).join('');
            var accountsList = document.getElementById('connected-accounts-list');
            if (accountsList) accountsList.innerHTML = accountsHtml;
        } else {
            resultDiv.innerHTML = '';
            var span = document.createElement('span');
            span.style.color = 'var(--red)';
            span.textContent = S.connectionFailed + data.error;
            resultDiv.appendChild(span);
        }
    })
    .finally(function() { btn.disabled = false; });
}

/* ── Platform Connections ── */
function showSimpleConnect(platform) {
    var el = document.getElementById('connect-' + platform);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function saveSimpleConnect(platform) {
    var btn = document.getElementById('save-' + platform + '-btn');
    if (btn) btn.disabled = true;
    var resultEl = document.getElementById('connect-' + platform + '-result');
    if (!resultEl) { if (btn) btn.disabled = false; return; }
    var serverName, credentials = {};
    if (platform === 'website') {
        serverName = 'seo';
        credentials = { cms_type: (document.getElementById('website-type') || {}).value || 'other', site_url: (document.getElementById('website-url') || {}).value || '' };
    } else if (platform === 'email') {
        serverName = 'email';
        credentials = { provider: 'smtp', smtp_host: 'smtp.gmail.com', smtp_port: '587', smtp_username: (document.getElementById('email-address') || {}).value || '', smtp_password: (document.getElementById('email-password') || {}).value || '' };
    } else {
        resultEl.innerHTML = '<span style="color:var(--green);">' + S.connectSuccess + escapeHtml(platform) + '.</span>';
        if (btn) btn.disabled = false;
        return;
    }
    resultEl.innerHTML = '<span style="color:var(--blue);">' + S.saving + '</span>';
    fetch('/api/mcp/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_name: serverName, platform: platform, credentials: credentials })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        resultEl.innerHTML = data.success
            ? '<span style="color:var(--green);">' + S.connectSuccess + escapeHtml(platform) + '.</span>'
            : '<span style="color:var(--red);">' + S.connectError + escapeHtml(data.error || 'Please try again.') + '</span>';
    })
    .catch(function() { resultEl.innerHTML = '<span style="color:var(--red);">' + S.connectFail + '</span>'; })
    .finally(function() { if (btn) btn.disabled = false; });
}

/* ── Utility ── */
function escapeHtml(t) {
    var d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
}

/* ── MCP Servers ── */
function loadMCPServers() {
    fetch('/api/mcp/servers')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var servers = data.servers || {};
            var keys = Object.keys(servers);
            var list = document.getElementById('mcp-server-list');
            if (!list) return;
            if (!keys.length) { list.innerHTML = '<p class="empty">' + S.noMCPServers + '</p>'; return; }
            var icons = { seo: '\ud83d\udd0d', social: '\ud83d\udcf1', email: '\ud83d\udce7', gmb: '\ud83d\udccd', ads: '\ud83d\udcb0', analytics: '\ud83d\udcca', website: '\ud83c\udf10', ecommerce: '\ud83d\uded2' };
            list.innerHTML = keys.map(function(k) {
                var s = servers[k];
                var icon = icons[k] || '\ud83d\udd0c';
                return '<div class="agent-card enabled" style="padding:16px;">'
                    + '<strong>' + icon + ' ' + escapeHtml(s.name || k) + '</strong>'
                    + '<p style="font-size:0.82rem;color:var(--gray-500);margin:4px 0;">' + escapeHtml(s.description || '') + '</p>'
                    + '<span class="badge badge-idle">' + (s.tools || 0) + S.tools + '</span></div>';
            }).join('');
        })
        .catch(function() {
            var list = document.getElementById('mcp-server-list');
            if (list) list.innerHTML = '<p class="empty">' + S.mcpLoadFailed + '</p>';
        });
}

/* ── PWA ── */
window.addEventListener('beforeinstallprompt', function(e) {
    e.preventDefault();
    deferredPrompt = e;
});

function installApp() {
    if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function() { deferredPrompt = null; });
    } else {
        var isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
        var isSafari = /safari/i.test(navigator.userAgent) && !/chrome/i.test(navigator.userAgent);
        toast(isIOS || isSafari ? S.installSafari : S.installBrowser);
    }
}

/* ── Keyboard helpers ── */
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeAddUser();
    if (e.key === 'Tab') trapModalFocus(e);
});

/* ── Bootstrap (run immediately, DOM is ready since script loads at end of body) ── */

(function() {

    // ── Sidebar tab navigation ──
    document.querySelectorAll('.sidebar-nav a[data-tab]').forEach(function(link) {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            switchTab(this.dataset.tab);
        });
    });

    // Initial data loads
    loadPersonalities().then(function() { loadAgents(); if (typeof populateAgentSelect === 'function') populateAgentSelect(); });
    loadApprovals();
    loadPendingExecutions();
    loadExecutions();
    loadExecutionerSettings();
    updateDashboard();
    loadUsers();
    loadMCPServers();

    // Auto-refresh
    setInterval(updateDashboard, 15000);

    // PWA
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js').catch(function(e) { console.error(e); });
    }

    // ── Register event listeners (element existence checked) ──

    var byId = function(id) { return document.getElementById(id); };

    // Sidebar (overlay, hamburger, install)
    var el = byId('overlay'); if (el) el.addEventListener('click', toggleSidebar);
    el = byId('hamburger-btn'); if (el) el.addEventListener('click', toggleSidebar);
    el = byId('sidebar-install-btn'); if (el) el.addEventListener('click', installApp);

    // Tenant
    el = byId('tenant-select'); if (el) el.addEventListener('change', function() { switchTenant(this.value); });

    // Dashboard (EN-only buttons, safe to try)
    el = byId('switch-tasks-btn'); if (el) el.addEventListener('click', function() { switchTab('tasks'); });
    el = byId('switch-analytics-btn'); if (el) el.addEventListener('click', function() { switchTab('analytics'); });
    el = byId('talk-to-agent-btn'); if (el) el.addEventListener('click', function() { if (window.chatWidget) chatWidget.toggle(); });

    // Approvals / Pending
    el = byId('refresh-approvals-btn'); if (el) el.addEventListener('click', loadApprovals);
    el = byId('refresh-pending-btn'); if (el) el.addEventListener('click', loadPendingExecutions);

    // Users
    el = byId('user-role-filter'); if (el) el.addEventListener('change', loadUsers);
    el = byId('show-add-user-btn'); if (el) el.addEventListener('click', showAddUser);
    el = byId('cancel-add-user-btn'); if (el) el.addEventListener('click', closeAddUser);
    el = byId('close-add-user-btn'); if (el) el.addEventListener('click', closeAddUser);
    el = byId('create-user-btn'); if (el) el.addEventListener('click', addUser);
    el = byId('add-user-btn'); if (el) el.addEventListener('click', addUser);

    // Platform connections
    el = byId('connect-shopify-btn'); if (el) el.addEventListener('click', function() { showSimpleConnect('shopify'); });
    el = byId('save-shopify-btn'); if (el) el.addEventListener('click', function() {
        var domain = (document.getElementById('shopify-domain') || {}).value || '';
        domain = domain.trim().toLowerCase();
        if (!domain) { toast('Please enter your Shopify store domain.'); return; }
        window.location.href = '/api/auth/install?shop=' + encodeURIComponent(domain);
    });
    el = byId('connect-website-btn'); if (el) el.addEventListener('click', function() { showSimpleConnect('website'); });
    el = byId('save-website-btn'); if (el) el.addEventListener('click', function() { saveSimpleConnect('website'); });
    el = byId('connect-facebook-btn'); if (el) el.addEventListener('click', function() { showSimpleConnect('facebook'); });
    el = byId('connect-fb-page-btn'); if (el) el.addEventListener('click', function() { toast('Facebook connection will open a popup. Make sure popups are allowed for this site.'); });
    el = byId('connect-email-toggle-btn'); if (el) el.addEventListener('click', function() { showSimpleConnect('email'); });
    el = byId('save-email-btn'); if (el) el.addEventListener('click', function() { saveSimpleConnect('email'); });
    el = byId('connect-google-toggle-btn'); if (el) el.addEventListener('click', function() { showSimpleConnect('google'); });
    el = byId('connect-tiktok-toggle-btn'); if (el) el.addEventListener('click', function() { showSimpleConnect('tiktok'); });

    // Settings
    el = byId('test-social-key-btn') || byId('validate-social-btn'); if (el) el.addEventListener('click', validateSocialApiKey);
    el = byId('reload-settings-btn'); if (el) el.addEventListener('click', loadExecutionerSettings);
    el = byId('save-settings-btn'); if (el) el.addEventListener('click', saveExecutionerSettings);
    el = byId('test-smtp-btn') || byId('test-email-btn'); if (el) el.addEventListener('click', function(e) { testSmtp(e); });

    // FR-specific: submit task, config agent
    el = byId('submit-task-btn'); if (el && typeof submitTask === 'function') el.addEventListener('click', submitTask);
    el = byId('config-agent-select'); if (el && typeof loadAgentConfig === 'function') el.addEventListener('change', loadAgentConfig);
    el = byId('detect-btn'); if (el && typeof detectModels === 'function') el.addEventListener('click', detectModels);
    el = byId('save-config-btn'); if (el && typeof saveAgentConfig === 'function') el.addEventListener('click', saveAgentConfig);

    // ── Event delegation ──

    // Agent cards
    el = byId('agent-list');
    if (el) {
        el.addEventListener('click', function(e) {
            var card = e.target.closest('.agent-card');
            if (!card) return;
            var agentId = card.dataset.agentId;
            if (e.target.closest('.chat-agent-btn, .chat-btn')) {
                window.location.href = (CFG.agentChatUrl || '/admin/agent/') + encodeURIComponent(agentId);
            } else if (e.target.closest('.toggle-agent-btn, .toggle-btn')) {
                toggleAgent(agentId);
            }
        });
    }

    // Approvals list
    el = byId('approvals-list');
    if (el) {
        el.addEventListener('click', function(e) {
            var card = e.target.closest('.approval-card');
            if (!card) return;
            var threadId = card.dataset.threadId;
            if (e.target.closest('.approve-btn')) {
                var btn = e.target.closest('.approve-btn');
                respondApproval(threadId, btn.dataset.approved !== 'false', btn);
            } else if (e.target.closest('.reject-show-btn, .show-reject-btn')) {
                var form = card.querySelector('.reject-form');
                if (form) form.style.display = 'block';
            } else if (e.target.closest('.reject-confirm-btn, .confirm-reject-btn')) {
                respondApproval(threadId, false, e.target.closest('.reject-confirm-btn, .confirm-reject-btn'));
            }
        });
    }

    // Pending executions
    el = byId('pending-executions-list');
    if (el) {
        el.addEventListener('click', function(e) {
            var card = e.target.closest('[data-exec-id], [data-execution-id]');
            if (!card) return;
            var execId = card.dataset.execId || card.dataset.executionId;
            if (e.target.closest('.confirm-exec-btn')) {
                confirmPending(execId, e.target.closest('.confirm-exec-btn'));
            } else if (e.target.closest('.reject-exec-btn')) {
                rejectPending(execId, e.target.closest('.reject-exec-btn'));
            }
        });
    }

    // Users list
    el = byId('users-list');
    if (el) {
        el.addEventListener('click', function(e) {
            var btn = e.target.closest('.delete-user-btn');
            if (btn) deleteUser(btn.dataset.userId, btn);
        });
    }
})();
