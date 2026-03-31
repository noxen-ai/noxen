/**
 * Noxen — Overview Tab Component
 */
function overviewComponent() {
  return {
    skillStats: null,
    qdrantStats: null,
    engineStatus: null,
    recentEvents: [],
    license: null,

    async init() {
      await this.loadAll();
      NoxenSSE.on('*', () => this.loadRecentEvents());
    },

    async loadAll() {
      await Promise.allSettled([
        this.loadSkillStats(),
        this.loadQdrantStats(),
        this.loadEngineStatus(),
        this.loadRecentEvents(),
        this.loadLicense(),
      ]);
    },

    async loadLicense() {
      try { this.license = await NoxenAPI.get('/api/tenants/license'); } catch(e) { this.license = null; }
    },

    async loadSkillStats() {
      try { this.skillStats = await NoxenAPI.skillStats(); } catch {}
    },

    async loadQdrantStats() {
      try { this.qdrantStats = await NoxenAPI.qdrantStats(); } catch {}
    },

    async loadEngineStatus() {
      try { this.engineStatus = await NoxenAPI.engineStatus(); } catch {}
    },

    async loadRecentEvents() {
      try {
        const events = await NoxenAPI.recentEvents(20);
        if (Array.isArray(events)) this.recentEvents = events;
      } catch {}
    },

    formatTime(ts) {
      if (!ts) return '';
      try {
        const d = new Date(ts);
        return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
      } catch { return ''; }
    },

    eventColor(source) {
      const map = {
        board: 'text-indigo-400', research: 'text-cyan-400', engine: 'text-emerald-400',
        notification: 'text-yellow-400', error: 'text-red-400', skill: 'text-purple-400',
      };
      return map[source] || 'text-gray-400';
    },
  };
}
