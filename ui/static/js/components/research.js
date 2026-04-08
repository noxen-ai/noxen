/**
 * Noxen — Research Tab Component
 */
function researchComponent() {
  return {
    query: '',
    selectedProject: '',
    projects: [],
    triggering: false,
    status: null,
    pendingSkills: [],
    researchLog: [],

    async init() {
      await Promise.allSettled([
        this.loadProjects(),
        this.loadStatus(),
        this.loadPendingSkills(),
      ]);
    },

    async loadProjects() {
      try {
        var data = await NoxenAPI.projects();
        this.projects = data?.projects || [];
      } catch(e) { this.projects = []; }
    },

    async loadStatus() {
      try { this.status = await NoxenAPI.researchStatus(); } catch {}
    },

    async loadPendingSkills() {
      try {
        const data = await NoxenAPI.skillPool('board_review');
        this.pendingSkills = data?.skills || data || [];
      } catch {}
    },

    async triggerResearch() {
      if (!this.query || this.triggering) return;
      this.triggering = true;
      this.researchLog = [];
      this.addLog('info', `Starting research: ${this.query}`);
      try {
        var context = this.selectedProject ? 'Project: ' + this.selectedProject : '';
        const result = await NoxenAPI.researchTrigger(this.query, context);
        this.addLog('success', `Research completed: ${result?.skills_found || 0} skills found`);
        await this.loadPendingSkills();
      } catch (e) {
        this.addLog('error', `Research failed: ${e.message}`);
      }
      this.triggering = false;
    },

    addLog(type, message) {
      const time = new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      this.researchLog.push({ time, type, message });
    },

    logColor(type) {
      const map = { success: 'text-green-400', error: 'text-red-400', warning: 'text-yellow-400', info: 'text-gray-400' };
      return map[type] || 'text-gray-400';
    },
  };
}
