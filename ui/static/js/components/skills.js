/**
 * Noxen — Skills Tab Component
 */
function skillsComponent() {
  return {
    skills: [],
    stats: null,
    filter: 'approved',
    searchQuery: '',
    loading: false,

    async init() {
      await Promise.allSettled([
        this.loadSkills(),
        this.loadStats(),
      ]);
    },

    async loadSkills() {
      this.loading = true;
      try {
        const data = await NoxenAPI.skillPool(this.filter);
        this.skills = data?.skills || data || [];
      } catch { this.skills = []; }
      this.loading = false;
    },

    async loadStats() {
      try { this.stats = await NoxenAPI.skillStats(); } catch {}
    },

    get filteredSkills() {
      if (!this.searchQuery) return this.skills;
      const q = this.searchQuery.toLowerCase();
      return this.skills.filter(s =>
        (s.name || '').toLowerCase().includes(q) ||
        (s.technology || '').toLowerCase().includes(q)
      );
    },

    async approveSkill(id) {
      try {
        await NoxenAPI.skillApprove(id);
        await this.loadSkills();
      } catch (e) { console.error('Approve failed:', e); }
    },

    async rejectSkill(id) {
      try {
        await NoxenAPI.skillReject(id);
        await this.loadSkills();
      } catch (e) { console.error('Reject failed:', e); }
    },

    confidenceColor(score) {
      if (score >= 0.8) return 'text-green-400';
      if (score >= 0.5) return 'text-yellow-400';
      return 'text-red-400';
    },

    confidenceBar(score) {
      const pct = Math.round((score || 0) * 100);
      let color = 'bg-red-500';
      if (score >= 0.8) color = 'bg-green-500';
      else if (score >= 0.5) color = 'bg-yellow-500';
      return { pct, color };
    },

    statusBadge(status) {
      const map = {
        approved: 'bg-green-900 text-green-300',
        draft: 'bg-gray-800 text-gray-400',
        board_review: 'bg-yellow-900 text-yellow-300',
        rejected: 'bg-red-900 text-red-300',
        deprecated: 'bg-gray-900 text-gray-500',
      };
      return map[status] || 'bg-gray-800 text-gray-400';
    },
  };
}
