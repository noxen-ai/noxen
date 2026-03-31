/**
 * Noxen — Board Tab Component
 */
function boardComponent() {
  return {
    decisions: [],

    async init() {
      await this.loadDecisions();
    },

    async loadDecisions() {
      try {
        const events = await NoxenAPI.boardDecisions(50);
        this.decisions = (Array.isArray(events) ? events : [])
          .filter(e => {
            const t = e.event_type || e.type || '';
            return t.includes('board') || t.includes('decision') || t.includes('deliberation');
          });
      } catch { this.decisions = []; }
    },

    formatTime(ts) {
      if (!ts) return '';
      try {
        const d = new Date(ts);
        return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
      } catch { return ''; }
    },

    decisionBadge(decision) {
      const map = {
        approved: 'bg-green-900 text-green-300',
        rejected: 'bg-red-900 text-red-300',
        deferred: 'bg-yellow-900 text-yellow-300',
        board_deliberation: 'bg-indigo-900 text-indigo-300',
      };
      return map[decision] || 'bg-gray-800 text-gray-400';
    },
  };
}
