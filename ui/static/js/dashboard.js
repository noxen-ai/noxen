/**
 * dashboard.js — Utility, navigazione tab, console, overview, repos, agents, bridge, terminale.
 * Estratto da dashboard.html per Step 0.2 (v0.3.0 Phase 0).
 * NOTE: innerHTML usage is preserved from original code — no functional changes.
 */

// ── Globals condivisi ──────────────────────────
var consoleEl = document.getElementById('console');

// ── Utility ──────────────────────────────
function fetchWithTimeout(url, options, timeoutMs) {
    timeoutMs = timeoutMs || 30000;
    var controller = new AbortController();
    var timer = setTimeout(function() { controller.abort(); }, timeoutMs);
    options = options || {};
    options.signal = controller.signal;
    return fetch(url, options).finally(function() { clearTimeout(timer); });
}

function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function createLogLine(msg, className) {
    var div = document.createElement('div');
    div.className = className;
    div.textContent = msg;
    return div;
}

// ── Tab Navigation ───────────────────────────
var ALL_TABS = ['overview', 'chat', 'skills', 'agents', 'llmsettings', 'bridge', 'terminal', 'guide'];
function showTab(name) {
    ALL_TABS.forEach(function(t) {
        document.getElementById('panel-' + t).classList.toggle('hidden', t !== name);
        var tab = document.getElementById('tab-' + t);
        tab.className = t === name
            ? 'pb-3 text-sm font-medium border-b-2 tab-active'
            : 'pb-3 text-sm font-medium border-b-2 tab-inactive';
    });
    if (name === 'overview') loadOverviewStats();
    if (name === 'chat') { loadChatStatus(); loadSpiderProjects(); loadEngineProjects(); }
    if (name === 'agents') loadAgents();
    if (name === 'llmsettings') loadLLMSettings();
    if (name === 'bridge') loadBridgeTools();
    if (name === 'terminal') initTerminal();
}

// ── Console ──────────────────────────────────
function log(msg, type) {
    type = type || 'info';
    var colors = { info: 'text-green-400', error: 'text-red-400', warn: 'text-yellow-400' };
    var ts = new Date().toLocaleTimeString();
    consoleEl.appendChild(createLogLine('[' + ts + '] ' + msg, colors[type] || colors.info));
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

// ── Overview Stats ───────────────────────────
async function loadOverviewStats() {
    try {
        var [statsRes, orchRes, qdrantRes] = await Promise.all([
            fetch('/api/plugins/stats'),
            fetch('/api/orchestrator/status'),
            fetch('/api/qdrant/status')
        ]);
        var stats = await statsRes.json();
        var orch = await orchRes.json();
        var qdrant = await qdrantRes.json();

        document.getElementById('ov-skills').textContent = stats.total_skills || 0;
        document.getElementById('ov-agents').textContent = stats.total_agents || 0;
        document.getElementById('hdr-skills').textContent = (stats.total_skills || 0) + ' skills | ' + (stats.total_agents || 0) + ' agents';

        // Knowledge Base
        var kb = orch.knowledge_base || {};
        var kbCount = kb.total_chunks || 0;
        document.getElementById('ov-kb').textContent = kbCount > 0 ? (kbCount > 1000 ? Math.round(kbCount / 1000) + 'K' : kbCount) : '-';
        document.getElementById('ov-kb-sub').textContent = kb.has_data ? 'documenti indicizzati' : 'non inizializzata';
        document.getElementById('hdr-kb').textContent = kbCount > 0 ? kbCount + ' docs KB' : 'KB vuota';

        // LLM & DB
        document.getElementById('ov-llm').textContent = orch.active_provider || 'N/A';
        document.getElementById('ov-llm-mode').textContent = orch.llm_mode === 'board' ? 'Board (CDA)' : 'Singolo';
        document.getElementById('ov-db').textContent = orch.db_connected ? 'Connesso' : 'Non connesso';
        document.getElementById('ov-db-sub').textContent = orch.db_tables ? orch.db_tables + ' tabelle' : '';

        // Qdrant Status
        var qdEl = document.getElementById('ov-qdrant');
        var qdSubEl = document.getElementById('ov-qdrant-sub');
        if (qdEl) {
            qdEl.textContent = qdrant.status === 'ok' ? 'Online' : qdrant.status || 'Offline';
            qdEl.style.color = qdrant.status === 'ok' ? '#4ade80' : '#f87171';
        }
        if (qdSubEl && qdrant.collections) {
            var totalPoints = 0;
            var collNames = Object.keys(qdrant.collections);
            for (var i = 0; i < collNames.length; i++) {
                totalPoints += qdrant.collections[collNames[i]].count || 0;
            }
            qdSubEl.textContent = collNames.length + ' collections, ' + totalPoints + ' punti';
        }

        // Qdrant collections detail
        var qdDetailEl = document.getElementById('ov-qdrant-detail');
        if (qdDetailEl && qdrant.collections) {
            while (qdDetailEl.firstChild) qdDetailEl.removeChild(qdDetailEl.firstChild);
            var collNames2 = Object.keys(qdrant.collections);
            for (var j = 0; j < collNames2.length; j++) {
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;justify-content:space-between;padding:2px 0;font-size:13px;';
                var nameSpan = document.createElement('span');
                nameSpan.textContent = collNames2[j];
                nameSpan.style.color = '#94a3b8';
                var countSpan = document.createElement('span');
                countSpan.textContent = qdrant.collections[collNames2[j]].count || 0;
                countSpan.style.color = '#e2e8f0';
                row.appendChild(nameSpan);
                row.appendChild(countSpan);
                qdDetailEl.appendChild(row);
            }
        }
    } catch (e) { /* ignora */ }
}

// ── Repository Installati ────────────────────
var _allReposData = [];

async function loadInstalledRepos() {
    var container = document.getElementById('installed-repos-grid');
    var label = document.getElementById('skills-count-label');
    try {
        var [iRes, pRes] = await Promise.all([
            fetch('/api/skills/installed'),
            fetch('/api/plugins/')
        ]);
        var installed = await iRes.json();
        var plugins = await pRes.json();

        var pluginMap = {};
        (plugins.plugins || []).forEach(function(p) {
            pluginMap[p.name] = p;
            var short = (p.name || '').split('/').pop();
            if (short) pluginMap[short] = p;
        });

        var repos = installed.skills || [];
        _allReposData = repos.map(function(r) {
            var p = pluginMap[r.name] || pluginMap[r.source] || {};
            return Object.assign({}, r, {
                skills_count: p.skill_count || 0,
                commands_count: p.command_count || 0,
                agents_count: p.agent_count || 0,
            });
        });
        label.textContent = repos.length + ' repository installati';
        renderRepoGrid(_allReposData);
    } catch (e) {
        container.textContent = 'Errore: ' + e.message;
    }
}

function filterRepos() {
    var q = (document.getElementById('repo-search').value || '').toLowerCase();
    if (!q) { renderRepoGrid(_allReposData); return; }
    var filtered = _allReposData.filter(function(r) {
        return (r.name || '').toLowerCase().indexOf(q) !== -1
            || (r.source || '').toLowerCase().indexOf(q) !== -1
            || (r.group || '').toLowerCase().indexOf(q) !== -1;
    });
    renderRepoGrid(filtered);
}

function renderRepoGrid(repos) {
    var container = document.getElementById('installed-repos-grid');
    if (!repos || repos.length === 0) {
        container.textContent = 'Nessun repository installato';
        return;
    }

    var groups = {};
    repos.forEach(function(r) {
        var g = r.group || '_root';
        if (!groups[g]) groups[g] = [];
        groups[g].push(r);
    });

    // Build DOM imperatively to avoid innerHTML
    container.textContent = '';
    Object.keys(groups).sort(function(a, b) {
        if (a === '_root') return -1;
        if (b === '_root') return 1;
        return a.localeCompare(b);
    }).forEach(function(gName) {
        var items = groups[gName];
        var groupDiv = document.createElement('div');
        groupDiv.className = 'mb-4';
        if (gName !== '_root') {
            var headerDiv = document.createElement('div');
            headerDiv.className = 'flex items-center gap-2 mb-2 px-1';
            var nameSpan = document.createElement('span');
            nameSpan.className = 'text-indigo-400 text-sm font-medium';
            nameSpan.textContent = gName + '/';
            var countSpan = document.createElement('span');
            countSpan.className = 'text-xs bg-gray-800 text-gray-500 px-1.5 py-0.5 rounded';
            countSpan.textContent = items.length + ' repo';
            headerDiv.appendChild(nameSpan);
            headerDiv.appendChild(countSpan);
            groupDiv.appendChild(headerDiv);
        }
        items.forEach(function(r) {
            var hasPlugin = r.skills_count > 0 || r.commands_count > 0 || r.agents_count > 0;
            var borderColor = hasPlugin ? 'border-indigo-800/50' : 'border-gray-800';
            var row = document.createElement('div');
            row.className = 'flex items-center justify-between bg-gray-900/50 border ' + borderColor + ' rounded-lg px-4 py-3 mb-1';

            var leftDiv = document.createElement('div');
            leftDiv.className = 'flex items-center gap-3 flex-wrap';
            var nameEl = document.createElement('span');
            nameEl.className = 'text-sm text-white font-medium';
            nameEl.textContent = r.name;
            leftDiv.appendChild(nameEl);
            var sourceEl = document.createElement('span');
            sourceEl.className = 'text-xs text-gray-600';
            sourceEl.textContent = r.source || '';
            leftDiv.appendChild(sourceEl);

            if (hasPlugin) {
                var badge = document.createElement('span');
                badge.className = 'text-xs bg-indigo-600/20 text-indigo-400 px-1.5 py-0.5 rounded';
                badge.textContent = r.skills_count + 's ' + r.commands_count + 'c ' + r.agents_count + 'a';
                leftDiv.appendChild(badge);
            } else {
                var ragBadge = document.createElement('span');
                ragBadge.className = 'text-xs bg-blue-900/20 text-blue-400 px-1.5 py-0.5 rounded';
                ragBadge.textContent = 'RAG docs';
                leftDiv.appendChild(ragBadge);
            }
            if (r.priority && r.priority !== 3) {
                var priBadge = document.createElement('span');
                priBadge.className = 'text-xs bg-gray-800 text-gray-500 px-1.5 py-0.5 rounded';
                priBadge.textContent = 'P' + r.priority;
                leftDiv.appendChild(priBadge);
            }
            row.appendChild(leftDiv);

            var rightDiv = document.createElement('div');
            rightDiv.className = 'flex items-center gap-2';
            var updBtn = document.createElement('button');
            updBtn.className = 'text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-1 rounded transition';
            updBtn.textContent = 'Aggiorna';
            updBtn.setAttribute('onclick', "updateInstalledSkill('" + r.name + "')");
            rightDiv.appendChild(updBtn);
            var delBtn = document.createElement('button');
            delBtn.className = 'text-xs bg-red-900/50 hover:bg-red-800/50 text-red-400 px-2 py-1 rounded transition';
            delBtn.textContent = 'Rimuovi';
            delBtn.setAttribute('onclick', "uninstallSkill('" + r.name + "')");
            rightDiv.appendChild(delBtn);
            row.appendChild(rightDiv);

            groupDiv.appendChild(row);
        });
        container.appendChild(groupDiv);
    });
}

async function scanPlugins() {
    log('Scansione plugin...');
    try {
        await fetch('/api/plugins/scan', { method: 'POST' });
        log('Scansione completata');
        loadInstalledRepos();
    } catch (e) { log('Errore scansione: ' + e.message, 'error'); }
}

// ── Agents Tab ───────────────────────────────
var _allAgentsData = [];
var _agentsLoaded = false;

var AGENT_GROUP_RULES = [
    { group: 'Security & Compliance', icon: '\uD83D\uDD12', keywords: ['security', 'secur', 'vulnerability', 'pentest', 'threat', 'owasp', 'compliance', 'audit'] },
    { group: 'Code Quality & Review', icon: '\uD83D\uDD0D', keywords: ['review', 'lint', 'quality', 'refactor', 'code review', 'clean code'] },
    { group: 'Testing & QA', icon: '\uD83E\uDDEA', keywords: ['test', 'testing', 'unit test', 'e2e', 'coverage', 'qa', 'pytest', 'jest'] },
    { group: 'Debugging', icon: '\uD83D\uDC1B', keywords: ['debug', 'error', 'bug', 'troubleshoot', 'diagnos'] },
    { group: 'DevOps & CI/CD', icon: '\u2699\uFE0F', keywords: ['devops', 'ci/cd', 'pipeline', 'deploy', 'docker', 'kubernetes', 'terraform'] },
    { group: 'Frontend & UI', icon: '\uD83C\uDFA8', keywords: ['frontend', 'react', 'vue', 'angular', 'css', 'ui', 'ux', 'component', 'tailwind'] },
    { group: 'Backend & API', icon: '\uD83D\uDD27', keywords: ['backend', 'api', 'rest', 'graphql', 'database', 'sql', 'microservice'] },
    { group: 'AI & Machine Learning', icon: '\uD83E\uDDE0', keywords: ['ai', 'machine learning', 'ml', 'llm', 'embedding', 'neural', 'prompt', 'rag'] },
    { group: 'Finance & Crypto', icon: '\uD83D\uDCB0', keywords: ['finance', 'crypto', 'blockchain', 'defi', 'trading'] },
    { group: 'Documentation', icon: '\uD83D\uDCDA', keywords: ['documentation', 'docs', 'readme', 'knowledge', 'guide'] },
    { group: 'Project Management', icon: '\uD83D\uDCCB', keywords: ['project', 'planning', 'roadmap', 'sprint', 'kanban'] },
    { group: 'Data & Analytics', icon: '\uD83D\uDCCA', keywords: ['data', 'analytics', 'dashboard', 'metrics', 'etl'] },
    { group: 'Architecture', icon: '\uD83C\uDFD7\uFE0F', keywords: ['architecture', 'design pattern', 'system design', 'ddd'] },
    { group: 'Performance', icon: '\u26A1', keywords: ['performance', 'optimization', 'cache', 'profiling'] },
];

var AGENT_GROUP_DESCRIPTIONS = {
    'Security & Compliance': 'Agenti specializzati in audit di sicurezza, vulnerability assessment, penetration testing, compliance GDPR/SOC2, threat modeling e protezione dati.',
    'Code Quality & Review': 'Revisione codice, analisi statica, identificazione code smell, violazioni SOLID, refactoring e best practice per codice pulito e manutenibile.',
    'Testing & QA': 'Generazione test suite, analisi coverage, strategie di testing (unit, integration, e2e), TDD e quality assurance automatizzata.',
    'Debugging': 'Investigazione bug con metodo scientifico, analisi stack trace, troubleshooting sistematico e diagnosi di errori complessi.',
    'DevOps & CI/CD': 'Pipeline CI/CD, containerizzazione Docker, orchestrazione Kubernetes, Infrastructure as Code, deploy automation e monitoring.',
    'Frontend & UI': 'Sviluppo e review componenti frontend, design system, accessibilita\', responsive design, performance rendering e UX.',
    'Backend & API': 'Architettura backend, design API REST/GraphQL, database optimization, microservizi, autenticazione e gestione dati.',
    'AI & Machine Learning': 'Prompt engineering, RAG pipeline, fine-tuning modelli, embedding, orchestrazione multi-agent e integrazione LLM.',
    'Finance & Crypto': 'DeFi, smart contract audit, analisi trading, portfolio management, risk assessment e blockchain development.',
    'Documentation': 'Generazione documentazione tecnica, API docs, knowledge base, onboarding guide e changelog automatizzati.',
    'Project Management': 'Pianificazione sprint, roadmap tecnica, estimation, backlog management e coordinamento team di sviluppo.',
    'Data & Analytics': 'ETL pipeline, data visualization, metriche, dashboard analytics, document analysis e business intelligence.',
    'Architecture': 'Design pattern, system design, architettura distribuita, DDD, event-driven architecture e decisioni tecnologiche.',
    'Performance': 'Profiling, ottimizzazione cache, memory management, bundle optimization, latency reduction e scalabilita\'.',
    'Accessibility': 'Audit WCAG, ARIA implementation, screen reader compatibility, keyboard navigation e inclusive design.',
    'Git & Collaboration': 'Git workflow, pull request review, branch strategy, merge conflict resolution e community management.',
    'Cloud & Infrastructure': 'AWS, Azure, GCP, serverless architecture, scaling, CDN, service mesh e cloud cost optimization.',
    'Mobile & Native': 'iOS, Android, React Native, Flutter, app performance, platform-specific patterns e app store optimization.',
    'SEO & Marketing': 'SEO tecnico, core web vitals, structured data, content strategy e conversion optimization.',
    'Scripting & Automation': 'Shell scripting, automazione task, CLI tool development, cron job e workflow automation.',
    'Altro': 'Agenti con competenze trasversali o specializzazioni non categorizzate.',
};

function classifyAgent(agent) {
    var text = ((agent.name || '') + ' ' + (agent.description || '')).toLowerCase();
    for (var i = 0; i < AGENT_GROUP_RULES.length; i++) {
        var rule = AGENT_GROUP_RULES[i];
        for (var j = 0; j < rule.keywords.length; j++) {
            if (text.indexOf(rule.keywords[j]) !== -1) return rule.group;
        }
    }
    return 'Altro';
}

function getGroupIcon(groupName) {
    for (var i = 0; i < AGENT_GROUP_RULES.length; i++) {
        if (AGENT_GROUP_RULES[i].group === groupName) return AGENT_GROUP_RULES[i].icon;
    }
    return '\uD83E\uDD16';
}

async function loadAgents() {
    var container = document.getElementById('agents-groups-grid');
    var label = document.getElementById('agents-count-label');
    var groupSelect = document.getElementById('agent-group-filter');
    var pluginSelect = document.getElementById('agent-plugin-filter');

    if (_agentsLoaded && _allAgentsData.length > 0) {
        renderAgentsGrouped(_allAgentsData);
        return;
    }

    container.textContent = 'Caricamento agenti...';

    try {
        var res = await fetch('/api/plugins/agents');
        var data = await res.json();
        _allAgentsData = data.agents || [];
        _agentsLoaded = true;

        label.textContent = _allAgentsData.length + ' agenti da ' + new Set(_allAgentsData.map(function(a) { return a.plugin; })).size + ' plugin';

        _allAgentsData.forEach(function(a) { a._group = classifyAgent(a); });

        var groups = {}, plugins = {};
        _allAgentsData.forEach(function(a) {
            groups[a._group] = (groups[a._group] || 0) + 1;
            plugins[a.plugin] = (plugins[a.plugin] || 0) + 1;
        });

        groupSelect.textContent = '';
        var allOpt = document.createElement('option');
        allOpt.value = '';
        allOpt.textContent = 'Tutti i gruppi (' + _allAgentsData.length + ')';
        groupSelect.appendChild(allOpt);
        Object.keys(groups).sort().forEach(function(g) {
            var opt = document.createElement('option');
            opt.value = g;
            opt.textContent = g + ' (' + groups[g] + ')';
            groupSelect.appendChild(opt);
        });

        pluginSelect.textContent = '';
        var allPlugOpt = document.createElement('option');
        allPlugOpt.value = '';
        allPlugOpt.textContent = 'Tutti i plugin';
        pluginSelect.appendChild(allPlugOpt);
        Object.keys(plugins).sort().forEach(function(p) {
            var opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p + ' (' + plugins[p] + ')';
            pluginSelect.appendChild(opt);
        });

        renderAgentsGrouped(_allAgentsData);
    } catch (e) {
        container.textContent = 'Errore: ' + e.message;
    }
}

function filterAgents() {
    var q = (document.getElementById('agent-search').value || '').toLowerCase();
    var groupFilter = document.getElementById('agent-group-filter').value;
    var pluginFilter = document.getElementById('agent-plugin-filter').value;

    var filtered = _allAgentsData.filter(function(a) {
        if (groupFilter && a._group !== groupFilter) return false;
        if (pluginFilter && a.plugin !== pluginFilter) return false;
        if (q) {
            var text = ((a.name || '') + ' ' + (a.description || '') + ' ' + (a.plugin || '')).toLowerCase();
            if (text.indexOf(q) === -1) return false;
        }
        return true;
    });

    document.getElementById('agents-count-label').textContent = filtered.length + ' di ' + _allAgentsData.length + ' agenti';
    renderAgentsGrouped(filtered);
}

function renderAgentsGrouped(agents) {
    var container = document.getElementById('agents-groups-grid');
    if (!agents || agents.length === 0) {
        container.textContent = 'Nessun agente trovato';
        return;
    }

    var grouped = {};
    agents.forEach(function(a) {
        var g = a._group || 'Altro';
        if (!grouped[g]) grouped[g] = [];
        grouped[g].push(a);
    });

    var sortedGroups = Object.keys(grouped).sort(function(a, b) {
        return grouped[b].length - grouped[a].length;
    });

    // Build DOM imperatively
    container.textContent = '';
    sortedGroups.forEach(function(groupName) {
        var items = grouped[groupName];
        var icon = getGroupIcon(groupName);
        var groupDesc = AGENT_GROUP_DESCRIPTIONS[groupName] || '';

        var wrapper = document.createElement('div');
        wrapper.className = 'bg-gray-900/30 border border-gray-800 rounded-xl overflow-hidden';

        var header = document.createElement('div');
        header.className = 'flex items-center justify-between px-5 py-3 bg-gray-900/60 cursor-pointer';
        header.setAttribute('onclick', 'toggleAgentGroup(this)');

        var headerLeft = document.createElement('div');
        headerLeft.className = 'flex-1 min-w-0';
        var titleRow = document.createElement('div');
        titleRow.className = 'flex items-center gap-3 mb-1';
        var iconSpan = document.createElement('span');
        iconSpan.className = 'text-xl';
        iconSpan.textContent = icon;
        var h3 = document.createElement('h3');
        h3.className = 'text-white font-medium';
        h3.textContent = groupName;
        var countBadge = document.createElement('span');
        countBadge.className = 'text-xs bg-indigo-600/20 text-indigo-400 px-2 py-0.5 rounded';
        countBadge.textContent = items.length;
        titleRow.appendChild(iconSpan);
        titleRow.appendChild(h3);
        titleRow.appendChild(countBadge);
        headerLeft.appendChild(titleRow);

        if (groupDesc) {
            var descP = document.createElement('p');
            descP.className = 'text-xs text-gray-500 leading-relaxed ml-9';
            descP.textContent = groupDesc;
            headerLeft.appendChild(descP);
        }
        header.appendChild(headerLeft);

        var chevron = document.createElement('span');
        chevron.className = 'text-gray-500 text-sm agent-chevron';
        chevron.textContent = '\u25B6';
        header.appendChild(chevron);
        wrapper.appendChild(header);

        var body = document.createElement('div');
        body.className = 'agent-group-body px-3 py-2 space-y-1';
        body.style.display = 'none';

        items.forEach(function(a) {
            var descShort = (a.description || '').length > 200 ? a.description.substring(0, 200) + '...' : (a.description || '');
            var agentRow = document.createElement('div');
            agentRow.className = 'flex items-start gap-3 bg-gray-950/50 rounded-lg px-4 py-3 hover:bg-gray-950/80 transition group';

            var infoDiv = document.createElement('div');
            infoDiv.className = 'flex-1 min-w-0';
            var nameRow = document.createElement('div');
            nameRow.className = 'flex items-center gap-2 mb-1';
            var nameSpan = document.createElement('span');
            nameSpan.className = 'text-sm text-white font-medium';
            nameSpan.textContent = a.name;
            var pluginSpan = document.createElement('span');
            pluginSpan.className = 'text-xs text-gray-600';
            pluginSpan.textContent = a.plugin;
            nameRow.appendChild(nameSpan);
            nameRow.appendChild(pluginSpan);
            infoDiv.appendChild(nameRow);
            var descEl = document.createElement('p');
            descEl.className = 'text-xs text-gray-400 leading-relaxed';
            descEl.textContent = descShort;
            infoDiv.appendChild(descEl);
            agentRow.appendChild(infoDiv);

            if (a.content) {
                var detailBtn = document.createElement('button');
                detailBtn.className = 'text-xs bg-gray-800 hover:bg-gray-700 text-gray-400 px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition shrink-0';
                detailBtn.textContent = 'Dettagli';
                detailBtn.setAttribute('onclick', "showAgentDetail('" + (a.name || '').replace(/'/g, "\\'") + "')");
                agentRow.appendChild(detailBtn);
            }
            body.appendChild(agentRow);
        });
        wrapper.appendChild(body);
        container.appendChild(wrapper);
    });
}

function toggleAgentGroup(headerEl) {
    var body = headerEl.nextElementSibling;
    var chevron = headerEl.querySelector('.agent-chevron');
    if (body.style.display === 'none') {
        body.style.display = '';
        chevron.textContent = '\u25BC';
    } else {
        body.style.display = 'none';
        chevron.textContent = '\u25B6';
    }
}

function showAgentDetail(agentName) {
    var agent = _allAgentsData.find(function(a) { return a.name === agentName; });
    if (!agent) return;

    var overlay = document.getElementById('agent-detail-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'agent-detail-overlay';
        overlay.className = 'fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6';
        overlay.onclick = function(e) { if (e.target === overlay) overlay.classList.add('hidden'); };
        document.body.appendChild(overlay);
    }

    var icon = getGroupIcon(agent._group);

    // Build overlay content with DOM methods
    overlay.textContent = '';
    var modal = document.createElement('div');
    modal.className = 'bg-gray-900 border border-gray-700 rounded-2xl max-w-3xl w-full max-h-[85vh] overflow-y-auto';

    var modalHeader = document.createElement('div');
    modalHeader.className = 'sticky top-0 bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between rounded-t-2xl';
    var headerInfo = document.createElement('div');
    headerInfo.className = 'flex items-center gap-3';
    var iconEl = document.createElement('span');
    iconEl.className = 'text-2xl';
    iconEl.textContent = icon;
    headerInfo.appendChild(iconEl);
    var titleDiv = document.createElement('div');
    var titleH2 = document.createElement('h2');
    titleH2.className = 'text-white font-semibold text-lg';
    titleH2.textContent = agent.name;
    titleDiv.appendChild(titleH2);
    var subtitleSpan = document.createElement('span');
    subtitleSpan.className = 'text-xs text-gray-500';
    subtitleSpan.textContent = agent.plugin + ' \u00B7 ' + agent._group;
    titleDiv.appendChild(subtitleSpan);
    headerInfo.appendChild(titleDiv);
    modalHeader.appendChild(headerInfo);

    var closeBtn = document.createElement('button');
    closeBtn.className = 'text-gray-500 hover:text-white text-xl px-2';
    closeBtn.textContent = '\u00D7';
    closeBtn.onclick = function() { overlay.classList.add('hidden'); };
    modalHeader.appendChild(closeBtn);
    modal.appendChild(modalHeader);

    var modalBody = document.createElement('div');
    modalBody.className = 'px-6 py-5';
    var contentBox = document.createElement('div');
    contentBox.className = 'bg-gray-950/50 rounded-xl p-5 text-sm text-gray-300 leading-relaxed whitespace-pre-wrap';
    contentBox.textContent = agent.content || agent.description || '';
    modalBody.appendChild(contentBox);
    modal.appendChild(modalBody);

    overlay.appendChild(modal);
    overlay.classList.remove('hidden');
}

// ── Bridge ───────────────────────────────────
async function loadBridgeTools() {
    try {
        var res = await fetch('/api/bridge/manifest');
        var data = await res.json();
        var select = document.getElementById('bridge-tool');
        while (select.children.length > 1) select.removeChild(select.lastChild);
        (data.tools || []).forEach(function(t) {
            var name = (t.function && t.function.name) || t.name;
            var opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        });
    } catch (e) { console.error(e); }
}

async function testBridge() {
    var tool = document.getElementById('bridge-tool').value;
    if (!tool) return;
    var res = await fetch('/api/bridge/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool: tool, arguments: {} }),
    });
    var data = await res.json();
    document.getElementById('bridge-result').textContent = JSON.stringify(data, null, 2);
}

// ── Terminale Multi-Scheda (xterm.js + WebSocket PTY) ────
var termSessions = {};
var termActiveId = null;
var termNextId = 1;
var termInited = false;

var TERM_THEME = {
    background: '#030712', foreground: '#e5e7eb', cursor: '#6366f1',
    cursorAccent: '#030712', selectionBackground: 'rgba(99, 102, 241, 0.3)',
    black: '#1f2937', red: '#ef4444', green: '#22c55e', yellow: '#eab308',
    blue: '#3b82f6', magenta: '#a855f7', cyan: '#06b6d4', white: '#e5e7eb',
    brightBlack: '#6b7280', brightRed: '#f87171', brightGreen: '#4ade80',
    brightYellow: '#facc15', brightBlue: '#60a5fa', brightMagenta: '#c084fc',
    brightCyan: '#22d3ee', brightWhite: '#f9fafb'
};

function initTerminal() {
    if (!termInited) {
        termInited = true;
        window.addEventListener('resize', function() {
            if (termActiveId && termSessions[termActiveId] && !document.getElementById('panel-terminal').classList.contains('hidden')) {
                termSessions[termActiveId].fit.fit();
            }
        });
    }
    if (Object.keys(termSessions).length === 0) {
        termAddTab();
    } else if (termActiveId && termSessions[termActiveId]) {
        termSessions[termActiveId].fit.fit();
        termSessions[termActiveId].term.focus();
    }
}

function termAddTab(name) {
    var id = 'term-' + termNextId++;
    var label = name || ('Shell ' + Object.keys(termSessions).length + 1);

    var panel = document.createElement('div');
    panel.id = 'termpanel-' + id;
    panel.className = 'absolute inset-0 hidden';
    document.getElementById('term-panels').appendChild(panel);

    var t = new window.Terminal({
        cursorBlink: true, cursorStyle: 'block', fontSize: 14,
        fontFamily: '"SF Mono", "Fira Code", Menlo, monospace',
        theme: TERM_THEME, allowProposedApi: true, scrollback: 5000
    });

    var fitAddon = new window.FitAddon.FitAddon();
    t.loadAddon(fitAddon);
    t.loadAddon(new window.WebLinksAddon.WebLinksAddon());
    t.open(panel);

    var session = { term: t, ws: null, fit: fitAddon, el: panel, name: label, status: 'disconnected' };
    termSessions[id] = session;

    t.onData(function(data) {
        if (session.ws && session.ws.readyState === WebSocket.OPEN) session.ws.send(data);
    });
    t.onResize(function(size) {
        if (session.ws && session.ws.readyState === WebSocket.OPEN)
            session.ws.send(JSON.stringify({ type: 'resize', rows: size.rows, cols: size.cols }));
    });

    termConnectSession(id);
    termSwitchTab(id);
    termRenderTabs();
    return id;
}

function termConnectSession(id) {
    var session = termSessions[id];
    if (!session) return;
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = protocol + '//' + location.host + '/api/terminal/ws';
    session.status = 'connecting';
    termRenderTabs();

    var ws = new WebSocket(wsUrl);
    session.ws = ws;
    ws.onopen = function() {
        session.status = 'connected';
        termRenderTabs();
        session.fit.fit();
        ws.send(JSON.stringify({ type: 'resize', rows: session.term.rows, cols: session.term.cols }));
    };
    ws.onmessage = function(event) { session.term.write(event.data); };
    ws.onclose = function() {
        session.status = 'disconnected';
        session.term.write('\r\n\x1b[90m--- Connessione terminata ---\x1b[0m\r\n');
        termRenderTabs();
    };
    ws.onerror = function() { session.status = 'disconnected'; termRenderTabs(); };
}

function termSwitchTab(id) {
    Object.keys(termSessions).forEach(function(sid) { termSessions[sid].el.classList.add('hidden'); });
    var session = termSessions[id];
    if (!session) return;
    session.el.classList.remove('hidden');
    termActiveId = id;
    setTimeout(function() { session.fit.fit(); session.term.focus(); }, 10);
    termRenderTabs();
}

function termCloseTab(id) {
    var session = termSessions[id];
    if (!session) return;
    if (session.ws) session.ws.close();
    session.term.dispose();
    session.el.remove();
    delete termSessions[id];
    if (termActiveId === id) {
        var remaining = Object.keys(termSessions);
        if (remaining.length > 0) termSwitchTab(remaining[remaining.length - 1]);
        else termActiveId = null;
    }
    termRenderTabs();
}

function termRenameTab(id) {
    var session = termSessions[id];
    if (!session) return;
    var tabEl = document.getElementById('tabtitle-' + id);
    if (!tabEl) return;
    var input = document.createElement('input');
    input.type = 'text';
    input.value = session.name;
    input.className = 'bg-gray-900 text-white text-xs border border-indigo-500 rounded px-1 py-0.5 w-20 outline-none';
    function commit() { var val = input.value.trim(); if (val) session.name = val; termRenderTabs(); }
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') termRenderTabs();
    });
    tabEl.textContent = '';
    tabEl.appendChild(input);
    input.focus();
    input.select();
}

function termRenderTabs() {
    var bar = document.getElementById('term-tabs-bar');
    bar.textContent = '';
    var ids = Object.keys(termSessions);
    ids.forEach(function(id) {
        var session = termSessions[id];
        var isActive = (id === termActiveId);

        var tab = document.createElement('div');
        tab.className = isActive
            ? 'flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 cursor-pointer'
            : 'flex items-center gap-1.5 bg-gray-900/50 border border-gray-800 rounded-lg px-3 py-1.5 cursor-pointer hover:bg-gray-800/50';

        var dot = document.createElement('span');
        dot.className = session.status === 'connected' ? 'w-1.5 h-1.5 bg-green-500 rounded-full flex-shrink-0'
            : session.status === 'connecting' ? 'w-1.5 h-1.5 bg-yellow-500 rounded-full flex-shrink-0 animate-pulse'
            : 'w-1.5 h-1.5 bg-gray-600 rounded-full flex-shrink-0';
        tab.appendChild(dot);

        var title = document.createElement('span');
        title.id = 'tabtitle-' + id;
        title.className = isActive ? 'text-xs text-white font-medium' : 'text-xs text-gray-400';
        title.textContent = session.name;
        tab.appendChild(title);

        tab.addEventListener('click', function(e) {
            if (e.target.dataset.action === 'close') return;
            termSwitchTab(id);
        });
        title.addEventListener('dblclick', function(e) { e.stopPropagation(); termRenameTab(id); });

        if (ids.length > 1) {
            var closeBtn = document.createElement('span');
            closeBtn.dataset.action = 'close';
            closeBtn.className = 'text-gray-500 hover:text-red-400 text-xs ml-1 leading-none cursor-pointer';
            closeBtn.textContent = '\u00D7';
            closeBtn.addEventListener('click', function(e) { e.stopPropagation(); termCloseTab(id); });
            tab.appendChild(closeBtn);
        }
        bar.appendChild(tab);
    });
}

function termReconnectActive() {
    if (!termActiveId || !termSessions[termActiveId]) return;
    var session = termSessions[termActiveId];
    if (session.ws) { session.ws.close(); session.ws = null; }
    session.term.clear();
    termConnectSession(termActiveId);
}

function termClearActive() {
    if (termActiveId && termSessions[termActiveId]) termSessions[termActiveId].term.clear();
}

// ── Init al caricamento ──────────────────────
loadOverviewStats();
loadInstalledRepos();
