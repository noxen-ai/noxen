/**
 * spider.js — Spider Analysis + Neural Engine.
 * Estratto da dashboard.html per Step 0.2 (v0.3.0 Phase 0).
 * NOTE: Some innerHTML usage preserved for trusted server-side content rendering.
 */

// ── Globals condivisi (definiti in dashboard.js / chat.js) ──
// log, escapeHtml — da dashboard.js

// ── Neural Engine ────────────────────────────
var _engineRunning = false;
var _lastEngineReport = '';

function loadEngineProjects() {
    fetch('/api/projects/').then(function(r){return r.json()}).then(function(data){
        var projects = data.projects || {};
        var select = document.getElementById('engine-project');
        select.textContent = '';
        var defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = '-- Seleziona progetto --';
        select.appendChild(defaultOpt);
        Object.keys(projects).forEach(function(name){
            var opt = document.createElement('option');
            opt.value = projects[name].path;
            opt.textContent = name;
            select.appendChild(opt);
        });
    }).catch(function(){});
}

async function startEngine() {
    var select = document.getElementById('engine-project');
    var projectPath = select.value;
    if (!projectPath) { alert('Seleziona un progetto prima'); return; }
    if (_engineRunning) return;
    _engineRunning = true;

    document.getElementById('btn-engine-start').classList.add('hidden');
    document.getElementById('btn-engine-stop').classList.remove('hidden');
    document.getElementById('engine-progress').classList.remove('hidden');
    document.getElementById('engine-goals-list').classList.remove('hidden');
    document.getElementById('engine-bar').style.width = '0%';
    document.getElementById('engine-phase').textContent = 'Avvio...';
    document.getElementById('engine-status').textContent = 'Connessione al motore...';
    document.getElementById('engine-goals-list').textContent = '';

    appendSystemMessage('\uD83E\uDDE0 Neural Engine avviato su ' + select.options[select.selectedIndex].text);

    try {
        var res = await fetch('/api/orchestrator/engine/start', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({project_path: projectPath})
        });

        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while(true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, {stream:true});

            var lines = buffer.split('\n');
            buffer = lines.pop();

            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (!line.startsWith('data: ')) continue;
                try {
                    var evt = JSON.parse(line.substring(6));
                    handleEngineEvent(evt);
                } catch(e) {}
            }
        }
    } catch(err) {
        document.getElementById('engine-status').textContent = 'Errore: ' + err.message;
    }

    _engineRunning = false;
    document.getElementById('btn-engine-start').classList.remove('hidden');
    document.getElementById('btn-engine-stop').classList.add('hidden');
}

function stopEngine() {
    fetch('/api/orchestrator/engine/stop', {method:'POST'}).then(function(){
        document.getElementById('engine-status').textContent = 'Stop richiesto...';
    });
}

function handleEngineEvent(evt) {
    var bar = document.getElementById('engine-bar');
    var phase = document.getElementById('engine-phase');
    var status = document.getElementById('engine-status');
    var goalsInfo = document.getElementById('engine-goals');

    var phaseLabels = {
        'bootstrap': 'Bootstrap',
        'inner_loop': 'Inner Loop',
        'outer_loop': 'Outer Loop',
        'cycle_start': 'Ciclo ' + (evt.cycle || ''),
        'loop_start': 'Loop Autonomo',
        'done': 'Completato',
        'stopped': 'Fermato',
        'error': 'Errore'
    };
    if (evt.phase && phaseLabels[evt.phase]) {
        phase.textContent = phaseLabels[evt.phase];
    }

    if (typeof evt.progress === 'number') {
        var totalProgress = 0;
        if (evt.phase === 'bootstrap' || evt.phase === 'start') {
            totalProgress = Math.round(evt.progress * 0.2);
        } else if (evt.phase === 'loop_start') {
            totalProgress = 20;
        } else if (evt.phase === 'cycle_start' || evt.phase === 'inner_loop' || evt.phase === 'outer_loop') {
            var goalsDone = evt.goals_done || 0;
            var goalsTotal = evt.goals_total || 1;
            totalProgress = 20 + Math.round((goalsDone / goalsTotal) * 70);
        } else if (evt.phase === 'done' || evt.phase === 'stopped') {
            totalProgress = 100;
        }
        bar.style.width = totalProgress + '%';
    }

    if (evt.detail) {
        status.textContent = evt.detail;
    }

    if (evt.goals_done !== undefined && evt.goals_total) {
        goalsInfo.textContent = evt.goals_done + '/' + evt.goals_total + ' goals completati';
    }

    if (evt.goals && Array.isArray(evt.goals)) {
        renderEngineGoals(evt.goals);
    }

    if (evt.goal_id && evt.goal_completed !== undefined) {
        var goalEl = document.getElementById('engine-goal-' + evt.goal_id);
        if (goalEl) {
            goalEl.className = evt.goal_completed
                ? 'text-[10px] px-2 py-1 rounded bg-emerald-900/30 text-emerald-400 border border-emerald-800/30'
                : 'text-[10px] px-2 py-1 rounded bg-red-900/30 text-red-400 border border-red-800/30';
        }
    }

    if (evt.phase === 'cycle_start') {
        appendSystemMessage('\uD83D\uDD04 Ciclo ' + evt.cycle + ': ' + (evt.goal ? evt.goal.title : ''));
    }
    if (evt.phase === 'inner_loop' && evt.step === 'executing') {
        appendSystemMessage('\u26A1 Claude Code in esecuzione...');
    }
    if (evt.phase === 'inner_loop' && evt.step === 'done') {
        appendSystemMessage('\uD83D\uDCE6 Claude Code: ' + (evt.files_changed || []).length + ' file modificati in ' + Math.round(evt.duration_s || 0) + 's');
    }
    if (evt.phase === 'outer_loop' && evt.step === 'evaluated') {
        var icon = evt.goal_completed ? '\u2705' : '\uD83D\uDD04';
        appendSystemMessage(icon + ' ' + (evt.detail || ''));
    }

    if (evt.done) {
        appendSystemMessage('\uD83C\uDFC1 Neural Engine completato: ' + (evt.detail || ''));
        if (evt.report) {
            _lastEngineReport = evt.report;
            // This is the one place we use a link - built from trusted app content
            var reportMsg = document.createElement('span');
            reportMsg.textContent = '\uD83D\uDCC4 Report finale disponibile \u2014 ';
            var reportLink = document.createElement('a');
            reportLink.href = '#';
            reportLink.className = 'text-indigo-400 underline';
            reportLink.textContent = 'Esporta .md';
            reportLink.onclick = function(e) { e.preventDefault(); exportEngineReport(); };
            reportMsg.appendChild(reportLink);
            var container = document.getElementById('chat-messages');
            var div = document.createElement('div');
            div.className = 'text-xs text-gray-400 py-1 px-3 bg-gray-900/30 rounded-lg border border-gray-800/50';
            div.appendChild(reportMsg);
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }
        bar.classList.remove('bg-emerald-500');
        bar.classList.add('bg-indigo-500');
    }
}

function renderEngineGoals(goals) {
    var container = document.getElementById('engine-goals-list');
    container.textContent = '';
    goals.forEach(function(g) {
        var icon = g.status === 'done' ? '\u2705' : g.status === 'skipped' ? '\u23ED\uFE0F' : g.status === 'in_progress' ? '\u26A1' : '\u23F3';
        var cls = g.status === 'done' ? 'bg-emerald-900/30 text-emerald-400 border-emerald-800/30'
                : g.status === 'in_progress' ? 'bg-yellow-900/30 text-yellow-400 border-yellow-800/30'
                : 'bg-gray-900/30 text-gray-500 border-gray-800/30';

        var goalDiv = document.createElement('div');
        goalDiv.id = 'engine-goal-' + g.id;
        goalDiv.className = 'text-[10px] px-2 py-1 rounded border ' + cls;

        var titleSpan = document.createElement('span');
        titleSpan.className = 'font-medium';
        titleSpan.textContent = g.title;
        var metaSpan = document.createElement('span');
        metaSpan.className = 'text-gray-600';
        metaSpan.textContent = ' [P' + g.priority + ' ' + g.category + ']';

        goalDiv.textContent = icon + ' ';
        goalDiv.appendChild(titleSpan);
        goalDiv.appendChild(metaSpan);
        container.appendChild(goalDiv);
    });
}

function appendSystemMessage(text) {
    var container = document.getElementById('chat-messages');
    var div = document.createElement('div');
    div.className = 'text-xs text-gray-400 py-1 px-3 bg-gray-900/30 rounded-lg border border-gray-800/50';
    div.textContent = text;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function exportEngineReport() {
    if (!_lastEngineReport) return;
    var blob = new Blob([_lastEngineReport], {type:'text/markdown'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'neural-engine-report.md';
    a.click();
    URL.revokeObjectURL(url);
}

// ── Spider Analysis ──────────────────────────
var _spiderRunning = false;
var _lastSpiderMarkdown = '';
var _spiderProjects = {};

async function loadSpiderProjects() {
    var select = document.getElementById('spider-project');
    try {
        var res = await fetch('/api/projects/');
        var data = await res.json();
        _spiderProjects = data.projects || {};
        select.textContent = '';
        var defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = '-- Seleziona progetto --';
        select.appendChild(defaultOpt);
        var names = Object.keys(_spiderProjects).sort();
        names.forEach(function(name) {
            var opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        });
        if (names.length === 0) {
            select.textContent = '';
            var emptyOpt = document.createElement('option');
            emptyOpt.value = '';
            emptyOpt.textContent = 'Nessun progetto registrato';
            select.appendChild(emptyOpt);
        }
    } catch (e) { /* ignora */ }
}

function onSpiderProjectChange() {
    // No-op per ora
}

async function runSpider(mode) {
    if (_spiderRunning) return;
    var select = document.getElementById('spider-project');
    var projectName = select.value;
    if (!projectName || !_spiderProjects[projectName]) {
        log('Seleziona un progetto registrato', 'error');
        select.focus();
        return;
    }
    var projectPath = _spiderProjects[projectName].path;

    _spiderRunning = true;
    _lastSpiderMarkdown = '';
    var progressEl = document.getElementById('spider-progress');
    var barEl = document.getElementById('spider-bar');
    var statusEl = document.getElementById('spider-status');
    progressEl.classList.remove('hidden');
    barEl.style.width = '0%';
    statusEl.textContent = 'Avvio Spider Analysis (' + mode + ')...';

    ['quick','deep','full'].forEach(function(m) {
        document.getElementById('btn-spider-' + m).disabled = true;
        document.getElementById('btn-spider-' + m).style.opacity = '0.5';
    });

    // Mostra nella chat
    var messagesEl = document.getElementById('chat-messages');
    var headerDiv = document.createElement('div');
    headerDiv.className = 'bg-indigo-900/30 border border-indigo-700/30 rounded-lg p-3 text-sm';

    var headerTitle = document.createElement('div');
    headerTitle.className = 'flex items-center gap-2 text-indigo-400 font-medium mb-1';
    headerTitle.textContent = '\uD83D\uDD77\uFE0F Spider Analysis \u2014 ' + mode.toUpperCase();
    headerDiv.appendChild(headerTitle);
    var chatStatus = document.createElement('div');
    chatStatus.className = 'text-xs text-gray-500';
    chatStatus.id = 'spider-chat-status';
    chatStatus.textContent = 'Inizializzazione...';
    headerDiv.appendChild(chatStatus);
    messagesEl.appendChild(headerDiv);

    var reportDiv = document.createElement('div');
    reportDiv.className = 'chat-msg-ai rounded-lg p-4 text-sm whitespace-pre-wrap hidden';
    reportDiv.id = 'spider-report-div';
    messagesEl.appendChild(reportDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
        var res = await fetch('/api/orchestrator/spider', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_path: projectPath, mode: mode }),
        });

        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
            var result = await reader.read();
            if (result.done) break;

            buffer += decoder.decode(result.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop();

            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (!line.startsWith('data: ')) continue;
                try {
                    var data = JSON.parse(line.substring(6));

                    if (data.error) {
                        statusEl.textContent = 'Errore: ' + data.error;
                        document.getElementById('spider-chat-status').textContent = 'Errore: ' + data.error;
                        log('Spider errore: ' + data.error, 'error');
                    }

                    if (data.progress !== undefined) {
                        barEl.style.width = data.progress + '%';
                    }
                    if (data.detail) {
                        statusEl.textContent = data.detail;
                        document.getElementById('spider-chat-status').textContent = data.detail;
                    }

                    if (data.report_markdown) {
                        _lastSpiderMarkdown = data.report_markdown;
                        reportDiv.textContent = data.report_markdown;
                        reportDiv.classList.remove('hidden');
                        messagesEl.scrollTop = messagesEl.scrollHeight;
                    }

                    if (data.done) {
                        var score = data.health_score || 0;
                        var scoreColor = score >= 75 ? 'text-green-400' : score >= 50 ? 'text-yellow-400' : 'text-red-400';

                        // Rebuild header with completion info
                        headerDiv.textContent = '';
                        var completionRow = document.createElement('div');
                        completionRow.className = 'flex items-center justify-between';
                        var completionTitle = document.createElement('div');
                        completionTitle.className = 'flex items-center gap-2 text-indigo-400 font-medium';
                        completionTitle.textContent = '\uD83D\uDD77\uFE0F Spider Analysis \u2014 ' + mode.toUpperCase() + ' completata';
                        completionRow.appendChild(completionTitle);

                        var rightDiv = document.createElement('div');
                        rightDiv.className = 'flex items-center gap-3';
                        var scoreSpan = document.createElement('span');
                        scoreSpan.className = scoreColor + ' font-bold';
                        scoreSpan.textContent = 'Score: ' + score + '/100';
                        rightDiv.appendChild(scoreSpan);
                        var exportBtn = document.createElement('button');
                        exportBtn.className = 'text-xs bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1 rounded transition';
                        exportBtn.textContent = 'Esporta .md';
                        exportBtn.onclick = function() { exportSpiderReport(); };
                        rightDiv.appendChild(exportBtn);
                        completionRow.appendChild(rightDiv);
                        headerDiv.appendChild(completionRow);

                        var detailDiv = document.createElement('div');
                        detailDiv.className = 'text-xs text-gray-500 mt-1';
                        detailDiv.textContent = data.detail || '';
                        headerDiv.appendChild(detailDiv);

                        log('Spider completata: score ' + score + '/100, ' + (data.total_issues || 0) + ' issue, ' + (data.agents_used || 0) + ' agenti');
                    }
                } catch (pe) { /* skip */ }
            }
        }
    } catch (e) {
        statusEl.textContent = 'Errore: ' + e.message;
        log('Spider errore: ' + e.message, 'error');
    }

    _spiderRunning = false;
    ['quick','deep','full'].forEach(function(m) {
        document.getElementById('btn-spider-' + m).disabled = false;
        document.getElementById('btn-spider-' + m).style.opacity = '1';
    });
}

function exportSpiderReport() {
    if (!_lastSpiderMarkdown) { log('Nessun report da esportare', 'warn'); return; }
    var blob = new Blob([_lastSpiderMarkdown], { type: 'text/markdown' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    var name = (document.getElementById('spider-project').value || 'project');
    a.download = 'spider-report-' + name + '-' + new Date().toISOString().slice(0,10) + '.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    log('Report esportato: ' + a.download);
}

// ── Init al caricamento ──────────────────────
loadSpiderProjects();
loadEngineProjects();
