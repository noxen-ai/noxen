/**
 * Noxen — Centralized API Client
 * All fetch calls go through NoxenAPI for consistency.
 */

const NoxenAPI = {
  _base: '',

  async _fetch(path, opts = {}) {
    const url = this._base + path;
    const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    const res = await fetch(url, { ...opts, headers });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new Error(`API ${res.status}: ${body}`);
    }
    return res.json();
  },

  get(path)        { return this._fetch(path); },
  post(path, body) { return this._fetch(path, { method: 'POST', body: JSON.stringify(body) }); },
  patch(path, body){ return this._fetch(path, { method: 'PATCH', body: JSON.stringify(body) }); },
  del(path)        { return this._fetch(path, { method: 'DELETE' }); },

  // ── Status ──────────────────────────────────
  status()         { return this.get('/api/orchestrator/status'); },

  // ── Chat ────────────────────────────────────
  chatModels()     { return this.get('/api/chat/models'); },

  // SSE streaming chat — returns raw Response for ReadableStream
  async chatStream(message, opts = {}) {
    const res = await fetch('/api/orchestrator/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, stream: true, ...opts }),
    });
    if (!res.ok) throw new Error(`Chat ${res.status}`);
    return res;
  },

  // ── Skills ──────────────────────────────────
  skillPool(status = 'approved')  { return this.get(`/api/skills/v2/pool?status=${status}`); },
  skillStats()                    { return this.get('/api/skills/v2/stats'); },
  skillAnalytics()                { return this.get('/api/skills/v2/analytics'); },
  skillApprove(id)                { return this.post(`/api/skills/v2/pool/${id}/approve`); },
  skillReject(id)                 { return this.post(`/api/skills/v2/pool/${id}/reject`); },
  skillSearch(query, tech, limit) { return this.post('/api/skills/v2/search', { query, technology: tech, limit: limit || 20 }); },

  // ── Research ────────────────────────────────
  researchStatus()                        { return this.get('/api/research/status'); },
  researchTrigger(query, context)         { return this.post('/api/research', { query, context }); },
  researchSearch(query)                   { return this.get(`/api/research/search?query=${encodeURIComponent(query)}`); },

  // ── Board (events-based) ────────────────────
  boardDecisions(limit = 50) { return this.get(`/api/events/recent?limit=${limit}`); },

  // ── Execution Engine ────────────────────────
  engineStart(projectPath, projectName)   { return this.post('/api/engine/start', { project_path: projectPath, project_name: projectName }); },
  engineStop()                            { return this.post('/api/engine/stop', {}); },
  engineStatus()                          { return this.get('/api/engine/status'); },
  engineApprove()                         { return this.post('/api/engine/approve', {}); },
  engineReject()                          { return this.post('/api/engine/reject', {}); },

  // ── Notifications ───────────────────────────
  notificationChannels()                  { return this.get('/api/notifications/channels'); },
  notificationApprovals()                 { return this.get('/api/notifications/approvals'); },
  notificationTest(channel)               { return this.post('/api/notifications/test', { channel }); },
  notificationApprove(approvalId, notes)  { return this.post('/api/notifications/approve', { approval_id: approvalId, notes }); },
  notificationReject(approvalId, reason)  { return this.post('/api/notifications/reject', { approval_id: approvalId, reason }); },

  // ── Events ──────────────────────────────────
  recentEvents(limit = 30)   { return this.get(`/api/events/recent?limit=${limit}`); },

  // ── Settings ────────────────────────────────
  getSettings()              { return this.get('/api/settings'); },
  getProviders()             { return this.get('/api/settings/providers'); },
  saveSettings(data)         { return this.post('/api/settings', data); },

  // ── Admin ───────────────────────────────────
  adminListTenants()                      { return this.get('/api/admin/tenants/'); },
  adminCreateTenant(data)                 { return this.post('/api/admin/tenants/', data); },
  adminDeleteTenant(id)                   { return this.del(`/api/admin/tenants/${id}`); },
  adminCreateApiKey(tenantId, keyName)    { return this.post(`/api/admin/tenants/${tenantId}/api-keys`, { key_name: keyName }); },
  adminTenantUsage(tenantId)              { return this.get(`/api/admin/tenants/${tenantId}/usage`); },

  // ── Qdrant ──────────────────────────────────
  qdrantStats()              { return this.get('/api/knowledge/status'); },

  // ── Projects ────────────────────────────────
  projects()                 { return this.get('/api/projects/'); },
};
