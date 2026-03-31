/**
 * settings.js — LLM settings, MySQL, skill install/update/uninstall.
 * Estratto da dashboard.html per Step 0.2 (v0.3.0 Phase 0).
 * NOTE: Some innerHTML usage preserved for trusted analysis report rendering.
 */

// ── Globals condivisi (definiti in dashboard.js) ──
// log, fetchWithTimeout, loadInstalledRepos — da dashboard.js

// ── Settings LLM ─────────────────────────────
async function loadLLMSettings() {
    try {
        var res = await fetch('/api/settings');
        var data = await res.json();
        var llm = data.llm || {};
        var radios = document.querySelectorAll('input[name="llm-mode"]');
        radios.forEach(function(r) { r.checked = r.value === llm.mode; });
        document.getElementById('chairman-row').classList.toggle('hidden', llm.mode !== 'board');
        if (llm.board_chairman) document.getElementById('board-chairman').value = llm.board_chairman;
    } catch (e) { /* ignora */ }
}

function updateLLMMode(mode) {
    document.getElementById('chairman-row').classList.toggle('hidden', mode !== 'board');
    fetch('/api/settings/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm_mode: mode }),
    }).then(function() { log('Modalita\' LLM: ' + mode); });
}

function updateChairman(val) {
    fetch('/api/settings/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ board_chairman: val }),
    }).then(function() { log('Chairman: ' + val); });
}

async function testProvider(provider) {
    var statusEl = document.getElementById(provider + '-status');
    statusEl.textContent = 'Testing...';
    statusEl.className = 'text-xs px-2 py-0.5 rounded bg-yellow-600/20 text-yellow-400';
    try {
        var res = await fetch('/api/settings/test-provider/' + provider, { method: 'POST' });
        var data = await res.json();
        if (data.success) {
            statusEl.textContent = 'OK ' + data.latency_ms + 'ms';
            statusEl.className = 'text-xs px-2 py-0.5 rounded bg-green-600/20 text-green-400';
        } else {
            statusEl.textContent = 'Errore';
            statusEl.className = 'text-xs px-2 py-0.5 rounded bg-red-600/20 text-red-400';
        }
    } catch (e) {
        statusEl.textContent = 'Errore';
        statusEl.className = 'text-xs px-2 py-0.5 rounded bg-red-600/20 text-red-400';
    }
}

async function saveProvider(provider) {
    var apiKey = '';
    var model = '';
    if (provider === 'ollama') {
        model = document.getElementById('ollama-model').value;
    } else {
        apiKey = document.getElementById(provider + '-key').value;
        if (apiKey === 'configurata') apiKey = '';
        model = document.getElementById(provider + '-model').value;
    }
    try {
        await fetch('/api/settings/provider', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: provider, api_key: apiKey, model: model }),
        });
        log('Provider salvato: ' + provider);
    } catch (e) {
        log('Errore salvataggio: ' + e.message, 'error');
    }
}

// ── MySQL Settings ───────────────────────────
async function saveMySQLSettings() {
    try {
        await fetch('/api/settings/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mysql_host: document.getElementById('mysql-host').value,
                mysql_port: parseInt(document.getElementById('mysql-port').value) || 3306,
                mysql_user: document.getElementById('mysql-user').value,
                mysql_password: document.getElementById('mysql-password').value,
                mysql_database: document.getElementById('mysql-database').value,
            }),
        });
        log('MySQL settings salvate');
    } catch (e) {
        log('Errore: ' + e.message, 'error');
    }
}

// ── Skill Install / Update / Uninstall ───────
var _pendingAnalysis = null;

async function analyzeBeforeInstall() {
    var urlInput = document.getElementById('skill-url');
    var btn = document.getElementById('btn-analyze-skill');
    var statusEl = document.getElementById('install-status');
    var reportEl = document.getElementById('analysis-report');
    var url = urlInput.value.trim();

    if (!url) { log('Inserisci un URL GitHub', 'error'); return; }

    reportEl.classList.add('hidden');
    _pendingAnalysis = null;
    btn.disabled = true;
    btn.textContent = 'Analisi in corso...';
    statusEl.classList.remove('hidden');
    statusEl.textContent = 'Clonazione temporanea e scansione del repository...';
    statusEl.className = 'mt-2 text-xs text-yellow-400';

    try {
        var res = await fetchWithTimeout('/api/skills/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url }),
        }, 120000);
        var data = await res.json();

        if (!res.ok) {
            statusEl.textContent = 'Errore analisi: ' + (data.detail || 'Sconosciuto');
            statusEl.className = 'mt-2 text-xs text-red-400';
            btn.disabled = false;
            btn.textContent = 'Analizza & Installa';
            return;
        }

        _pendingAnalysis = data;
        statusEl.classList.add('hidden');
        showAnalysisReport(data);
        log('Analisi completata per ' + data.repo_name + ' -- confidenza: ' + data.confidence);
    } catch (e) {
        var errMsg = e.name === 'AbortError'
            ? 'Timeout: analisi troppo lunga.'
            : 'Server non raggiungibile.';
        statusEl.textContent = errMsg;
        statusEl.className = 'mt-2 text-xs text-red-400';
        log(errMsg, 'error');
    }

    btn.disabled = false;
    btn.textContent = 'Analizza & Installa';
}

function showAnalysisReport(data) {
    var reportEl = document.getElementById('analysis-report');
    var headerEl = document.getElementById('analysis-header');
    var iconEl = document.getElementById('analysis-icon');
    var titleEl = document.getElementById('analysis-title');
    var badgeEl = document.getElementById('analysis-badge');
    var bodyEl = document.getElementById('analysis-body');
    var warningsEl = document.getElementById('analysis-warnings');
    var confirmBtn = document.getElementById('btn-confirm-install');
    var forceBtn = document.getElementById('btn-force-install');

    var confMap = {
        'high':   { icon: '\u2705', bg: 'bg-green-900/30', badge: 'bg-green-600 text-white', label: 'ALTA' },
        'medium': { icon: '\u26A0\uFE0F', bg: 'bg-yellow-900/20', badge: 'bg-yellow-600 text-white', label: 'MEDIA' },
        'low':    { icon: '\u26A0\uFE0F', bg: 'bg-orange-900/20', badge: 'bg-orange-600 text-white', label: 'BASSA' },
        'none':   { icon: '\u274C', bg: 'bg-red-900/20', badge: 'bg-red-600 text-white', label: 'NESSUNA' },
    };
    var conf = confMap[data.confidence] || confMap['none'];

    headerEl.className = 'px-4 py-3 flex items-center justify-between ' + conf.bg;
    iconEl.textContent = conf.icon;
    titleEl.textContent = data.owner + '/' + data.repo_name;
    badgeEl.textContent = 'Confidenza: ' + conf.label;
    badgeEl.className = 'text-xs px-2 py-0.5 rounded font-medium ' + conf.badge;

    // Build body with DOM methods
    var ind = data.skill_indicators || {};
    bodyEl.textContent = '';

    if (ind.plugin_manifest) {
        var pluginDiv = document.createElement('div');
        pluginDiv.className = 'text-green-400';
        var pluginStrong = document.createElement('strong');
        pluginStrong.textContent = 'Plugin: ';
        pluginDiv.appendChild(pluginStrong);
        pluginDiv.appendChild(document.createTextNode((ind.plugin_manifest.name || '') + ' v' + (ind.plugin_manifest.version || '?')));
        bodyEl.appendChild(pluginDiv);
    }

    var nativeItems = [];
    if (ind.has_plugin_json) nativeItems.push({text: 'plugin.json', cls: 'text-green-400'});
    if (ind.skill_md_count > 0) nativeItems.push({text: ind.skill_md_count + ' SKILL.md', cls: 'text-green-400'});
    if ((ind.command_files || []).length > 0) nativeItems.push({text: ind.command_files.length + ' comandi', cls: 'text-purple-400'});
    if ((ind.agent_files || []).length > 0) nativeItems.push({text: ind.agent_files.length + ' agenti', cls: 'text-cyan-400'});

    if (nativeItems.length > 0) {
        var nativeDiv = document.createElement('div');
        var nativeStrong = document.createElement('strong');
        nativeStrong.textContent = 'Skill Claude: ';
        nativeDiv.appendChild(nativeStrong);
        nativeItems.forEach(function(item, idx) {
            if (idx > 0) nativeDiv.appendChild(document.createTextNode(' \u00B7 '));
            var span = document.createElement('span');
            span.className = item.cls;
            span.textContent = item.text;
            nativeDiv.appendChild(span);
        });
        bodyEl.appendChild(nativeDiv);
    }

    var mdTotal = ind.markdown_files_total || 0;
    if (mdTotal > 0) {
        var ragDiv = document.createElement('div');
        var ragStrong = document.createElement('strong');
        ragStrong.textContent = 'Valore RAG: ';
        ragDiv.appendChild(ragStrong);
        ragDiv.appendChild(document.createTextNode(mdTotal + ' file .md'));
        bodyEl.appendChild(ragDiv);
    }

    var recTexts = {
        'install': {text: 'Installazione consigliata', cls: 'text-green-400 font-medium'},
        'caution': {text: 'Verifica manualmente', cls: 'text-yellow-400 font-medium'},
        'reject':  {text: 'Sconsigliato', cls: 'text-red-400 font-medium'},
    };
    if (recTexts[data.recommendation]) {
        var recDiv = document.createElement('div');
        recDiv.className = 'mt-2';
        var recSpan = document.createElement('span');
        recSpan.className = recTexts[data.recommendation].cls;
        recSpan.textContent = recTexts[data.recommendation].text;
        recDiv.appendChild(recSpan);
        bodyEl.appendChild(recDiv);
    }

    warningsEl.textContent = '';
    (data.warnings || []).forEach(function(w) {
        var wDiv = document.createElement('div');
        wDiv.className = 'text-xs text-yellow-500 bg-yellow-900/20 px-3 py-1.5 rounded';
        wDiv.textContent = '\u26A0 ' + w;
        warningsEl.appendChild(wDiv);
    });

    if (data.recommendation === 'reject') {
        confirmBtn.classList.add('hidden');
        forceBtn.classList.remove('hidden');
    } else {
        confirmBtn.classList.remove('hidden');
        forceBtn.classList.add('hidden');
    }
    reportEl.classList.remove('hidden');
}

async function confirmInstall() { if (_pendingAnalysis) await _doInstall(); }
async function forceInstall() {
    if (!_pendingAnalysis) return;
    if (!confirm('Questo repo NON sembra un plugin Claude Code.\nInstallare comunque?')) return;
    await _doInstall();
}
function cancelInstall() {
    _pendingAnalysis = null;
    document.getElementById('analysis-report').classList.add('hidden');
    document.getElementById('install-status').classList.add('hidden');
}

async function _doInstall() {
    var urlInput = document.getElementById('skill-url');
    var groupInput = document.getElementById('skill-group');
    var prioritySelect = document.getElementById('skill-priority');
    var statusEl = document.getElementById('install-status');
    var reportEl = document.getElementById('analysis-report');
    var url = urlInput.value.trim();
    if (!url) return;

    statusEl.classList.remove('hidden');
    statusEl.textContent = 'Installazione in corso...';
    statusEl.className = 'mt-2 text-xs text-yellow-400';

    try {
        var res = await fetchWithTimeout('/api/skills/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                group: groupInput.value.trim(),
                priority: parseInt(prioritySelect.value)
            }),
        }, 120000);
        var data = await res.json();
        if (res.ok) {
            statusEl.textContent = 'Installata: ' + data.skill.name;
            statusEl.className = 'mt-2 text-xs text-green-400';
            log('Skill installata: ' + data.skill.name);
            urlInput.value = '';
            reportEl.classList.add('hidden');
            _pendingAnalysis = null;
            setTimeout(function() { loadInstalledRepos(); }, 1000);
        } else {
            statusEl.textContent = 'Errore: ' + (data.detail || 'Sconosciuto');
            statusEl.className = 'mt-2 text-xs text-red-400';
        }
    } catch (e) {
        statusEl.textContent = e.name === 'AbortError' ? 'Timeout.' : 'Server non raggiungibile.';
        statusEl.className = 'mt-2 text-xs text-red-400';
    }
}

async function updateInstalledSkill(name) {
    log('Aggiornamento skill: ' + name + '...', 'warn');
    var res = await fetch('/api/skills/update/' + name, { method: 'POST' });
    var data = await res.json();
    log('[' + name + '] ' + data.result);
}

async function uninstallSkill(name) {
    if (!confirm('Disinstallare "' + name + '"?')) return;
    var res = await fetch('/api/skills/uninstall/' + name, { method: 'DELETE' });
    if (res.ok) { log('Skill disinstallata: ' + name); loadInstalledRepos(); }
    else { log('Errore disinstallazione', 'error'); }
}
