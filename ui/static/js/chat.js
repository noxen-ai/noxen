/**
 * chat.js — Chat SSE streaming, conversazioni localStorage, prompt helpers.
 * Estratto da dashboard.html per Step 0.2 (v0.3.0 Phase 0).
 */

// ── Globals condivisi (definiti in dashboard.js) ──
// consoleEl, escapeHtml, log — da dashboard.js

var chatHistory = [];
var _chatStreaming = false;

// ── Chat Status ──────────────────────────────
async function loadChatStatus() {
    try {
        var res = await fetch('/api/orchestrator/status');
        var data = await res.json();
        var dot = document.getElementById('chat-status-dot');
        var text = document.getElementById('chat-status-text');
        dot.className = 'w-2 h-2 rounded-full bg-green-500';
        text.textContent = 'Orchestratore attivo';
        text.className = 'text-green-400';

        var kb = data.knowledge_base || {};
        document.getElementById('chat-kb-info').textContent = 'KB: ' + (kb.total_chunks || 0) + ' docs';
        document.getElementById('chat-llm-info').textContent = 'LLM: ' + (data.active_provider || '-') + ' (' + (data.llm_mode || 'single') + ')';
    } catch (e) {
        document.getElementById('chat-status-dot').className = 'w-2 h-2 rounded-full bg-red-500';
        document.getElementById('chat-status-text').textContent = 'Orchestratore non raggiungibile';
        document.getElementById('chat-status-text').className = 'text-red-400';
    }
}

// ── Chat Send (SSE Streaming) ────────────────
async function sendChat() {
    if (_chatStreaming) return;
    var input = document.getElementById('chat-input');
    var msg = input.value.trim();
    if (!msg) return;

    var messagesEl = document.getElementById('chat-messages');
    var btn = document.getElementById('btn-chat-send');

    // User message
    var userDiv = document.createElement('div');
    userDiv.className = 'chat-msg-user rounded-lg p-3 text-sm whitespace-pre-wrap';
    userDiv.textContent = msg;
    messagesEl.appendChild(userDiv);
    input.value = '';

    // AI response placeholder (streaming)
    var aiDiv = document.createElement('div');
    aiDiv.className = 'chat-msg-ai rounded-lg p-3 text-sm whitespace-pre-wrap';
    var cursor = document.createElement('span');
    cursor.className = 'typing-cursor';
    aiDiv.appendChild(cursor);
    messagesEl.appendChild(aiDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    chatHistory.push({ role: 'user', content: msg });
    _chatStreaming = true;
    btn.disabled = true;
    btn.textContent = '...';

    var fullResponse = '';

    try {
        var res = await fetch('/api/orchestrator/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: msg,
                history: chatHistory.slice(-20),
                stream: true,
            }),
        });

        if (!res.ok) {
            var errData = await res.json();
            throw new Error(errData.detail || 'Errore ' + res.status);
        }

        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
            var result = await reader.read();
            if (result.done) break;

            buffer += decoder.decode(result.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete line

            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (!line.startsWith('data: ')) continue;
                try {
                    var payload = JSON.parse(line.substring(6));
                    if (payload.token) {
                        fullResponse += payload.token;
                        aiDiv.textContent = fullResponse;
                        messagesEl.scrollTop = messagesEl.scrollHeight;
                    }
                    if (payload.done) {
                        // streaming complete
                    }
                    if (payload.error) {
                        fullResponse += '\n[Errore: ' + payload.error + ']';
                        aiDiv.textContent = fullResponse;
                    }
                } catch (pe) { /* skip malformed SSE */ }
            }
        }

        if (!fullResponse) {
            aiDiv.textContent = 'Nessuna risposta ricevuta.';
        }
        chatHistory.push({ role: 'assistant', content: fullResponse });
        autoSaveConversation();

    } catch (e) {
        aiDiv.textContent = 'Errore: ' + e.message;
        aiDiv.classList.add('text-red-400');
    }

    _chatStreaming = false;
    btn.disabled = false;
    btn.textContent = 'Invia';
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function clearChat() {
    chatHistory = [];
    var el = document.getElementById('chat-messages');
    el.textContent = '';
    var resetMsg = document.createElement('div');
    resetMsg.className = 'chat-msg-ai rounded-lg p-3 text-sm';
    resetMsg.textContent = 'Chat pulita. Chiedimi qualsiasi cosa!';
    el.appendChild(resetMsg);
}

// ── Conversazioni (localStorage) ─────────────
var _conversations = JSON.parse(localStorage.getItem('nh_conversations') || '[]');
var _activeConvId = null;

function _saveConversations() {
    // Mantieni max 30 conversazioni
    if (_conversations.length > 30) _conversations = _conversations.slice(-30);
    localStorage.setItem('nh_conversations', JSON.stringify(_conversations));
}

function _getConvTitle(history) {
    // Prima domanda utente come titolo (max 50 chars)
    for (var i = 0; i < history.length; i++) {
        if (history[i].role === 'user') {
            var t = history[i].content.substring(0, 50);
            return t.length < history[i].content.length ? t + '...' : t;
        }
    }
    return 'Conversazione vuota';
}

function autoSaveConversation() {
    if (chatHistory.length < 2) return; // Almeno 1 domanda + 1 risposta
    var title = _getConvTitle(chatHistory);
    var now = new Date().toISOString();

    if (_activeConvId) {
        // Aggiorna conversazione esistente
        var conv = _conversations.find(function(c) { return c.id === _activeConvId; });
        if (conv) {
            conv.history = chatHistory.slice();
            conv.title = title;
            conv.updated = now;
            conv.msgCount = chatHistory.length;
        }
    } else {
        // Nuova conversazione
        _activeConvId = 'conv_' + Date.now();
        _conversations.push({
            id: _activeConvId,
            title: title,
            history: chatHistory.slice(),
            created: now,
            updated: now,
            msgCount: chatHistory.length,
        });
    }
    _saveConversations();
    renderConversationsList();
}

function newConversation() {
    // Salva corrente se ha contenuto
    if (chatHistory.length >= 2) autoSaveConversation();
    _activeConvId = null;
    chatHistory = [];
    var el = document.getElementById('chat-messages');
    el.textContent = '';
    var resetMsg = document.createElement('div');
    resetMsg.className = 'chat-msg-ai rounded-lg p-3 text-sm';
    resetMsg.textContent = 'Nuova conversazione. Chiedimi qualsiasi cosa!';
    el.appendChild(resetMsg);
    renderConversationsList();
}

function loadConversation(convId) {
    var conv = _conversations.find(function(c) { return c.id === convId; });
    if (!conv) return;

    // Salva corrente prima di cambiare
    if (_activeConvId && _activeConvId !== convId && chatHistory.length >= 2) autoSaveConversation();

    _activeConvId = convId;
    chatHistory = conv.history.slice();

    // Ricostruisci i messaggi nel DOM
    var el = document.getElementById('chat-messages');
    el.textContent = '';
    chatHistory.forEach(function(m) {
        var div = document.createElement('div');
        div.className = (m.role === 'user' ? 'chat-msg-user' : 'chat-msg-ai') + ' rounded-lg p-3 text-sm whitespace-pre-wrap';
        div.textContent = m.content;
        el.appendChild(div);
    });
    el.scrollTop = el.scrollHeight;
    renderConversationsList();
}

function deleteConversation(convId, e) {
    e.stopPropagation();
    _conversations = _conversations.filter(function(c) { return c.id !== convId; });
    if (_activeConvId === convId) _activeConvId = null;
    _saveConversations();
    renderConversationsList();
}

function renderConversationsList() {
    var container = document.getElementById('chat-conversations-list');
    if (_conversations.length === 0) {
        container.textContent = '';
        var empty = document.createElement('div');
        empty.className = 'text-xs text-gray-600 text-center py-2';
        empty.textContent = 'Nessuna conversazione salvata';
        container.appendChild(empty);
        return;
    }

    // Build DOM imperatively
    container.textContent = '';
    var sorted = _conversations.slice().reverse();
    sorted.forEach(function(c) {
        var isActive = c.id === _activeConvId;
        var date = new Date(c.updated);
        var timeStr = date.toLocaleDateString('it', {day:'2-digit', month:'short'}) + ' ' + date.toLocaleTimeString('it', {hour:'2-digit', minute:'2-digit'});

        var row = document.createElement('div');
        row.className = 'flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer group '
            + (isActive ? 'bg-indigo-600/20 border border-indigo-600/30' : 'hover:bg-gray-800/50 border border-transparent');
        row.setAttribute('onclick', "loadConversation('" + c.id + "')");

        var infoDiv = document.createElement('div');
        infoDiv.className = 'flex-1 min-w-0';
        var titleDiv = document.createElement('div');
        titleDiv.className = 'text-xs ' + (isActive ? 'text-white font-medium' : 'text-gray-300') + ' truncate';
        titleDiv.textContent = c.title;
        infoDiv.appendChild(titleDiv);
        var metaDiv = document.createElement('div');
        metaDiv.className = 'text-xs text-gray-600';
        metaDiv.textContent = timeStr + ' \u00B7 ' + c.msgCount + ' msg';
        infoDiv.appendChild(metaDiv);
        row.appendChild(infoDiv);

        var delBtn = document.createElement('button');
        delBtn.className = 'text-xs text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition px-1';
        delBtn.textContent = '\u00D7';
        delBtn.setAttribute('onclick', "deleteConversation('" + c.id + "', event)");
        row.appendChild(delBtn);

        container.appendChild(row);
    });
}

// ── Prompt ottimizzati ───────────────────────
function usePrompt(btnEl) {
    var prompt = btnEl.getAttribute('data-prompt');
    if (!prompt) return;
    document.getElementById('chat-input').value = prompt;
    document.getElementById('chat-input').focus();
}

// ── Init conversazioni al caricamento ────────
renderConversationsList();
