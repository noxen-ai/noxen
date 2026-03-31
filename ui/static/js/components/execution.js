/**
 * Noxen — Execution Engine Tab Component
 */
function executionComponent() {
  return {
    projectPath: '',
    projectName: '',
    starting: false,
    sessionStatus: null,
    approvalPending: false,
    goals: [],
    sseLog: [],

    async init() {
      await this.loadStatus();

      NoxenSSE.on('awaiting_approval', () => {
        this.approvalPending = true;
        this.addLog('warning', 'Plan awaiting approval');
      });
      NoxenSSE.on('session_complete', () => {
        this.addLog('success', 'Session completed');
        this.loadStatus();
      });
      NoxenSSE.on('goal_completed', (e) => {
        this.addLog('success', `Goal completed: ${e.data?.title || ''}`);
        this.loadStatus();
      });
    },

    async loadStatus() {
      try {
        const data = await NoxenAPI.engineStatus();
        this.sessionStatus = data;
        this.goals = data?.goals || [];
        this.approvalPending = data?.awaiting_approval || false;
      } catch {}
    },

    async startEngine() {
      if (!this.projectPath || this.starting) return;
      this.starting = true;
      this.sseLog = [];
      this.addLog('info', `Starting engine for ${this.projectPath}`);
      try {
        const result = await NoxenAPI.engineStart(this.projectPath, this.projectName);
        this.addLog('success', `Engine started: session ${result?.session_id || 'unknown'}`);
        await this.loadStatus();
      } catch (e) {
        this.addLog('error', `Start failed: ${e.message}`);
      }
      this.starting = false;
    },

    async stopEngine() {
      try {
        await NoxenAPI.engineStop();
        this.addLog('info', 'Engine stopped');
        await this.loadStatus();
      } catch (e) {
        this.addLog('error', `Stop failed: ${e.message}`);
      }
    },

    async approveAll() {
      try {
        await NoxenAPI.engineApprove();
        this.approvalPending = false;
        this.addLog('success', 'Plan approved');
      } catch (e) {
        this.addLog('error', `Approve failed: ${e.message}`);
      }
    },

    async rejectPlan() {
      try {
        await NoxenAPI.engineReject();
        this.approvalPending = false;
        this.addLog('info', 'Plan rejected');
      } catch (e) {
        this.addLog('error', `Reject failed: ${e.message}`);
      }
    },

    addLog(type, message) {
      const time = new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      this.sseLog.unshift({ time, type, message });
      if (this.sseLog.length > 200) this.sseLog.length = 200;
    },

    goalStatusColor(status) {
      const map = { completed: 'text-green-400', in_progress: 'text-yellow-400', pending: 'text-gray-500', failed: 'text-red-400' };
      return map[status] || 'text-gray-500';
    },

    goalStatusIcon(status) {
      const map = { completed: '\u2713', in_progress: '\u25B6', pending: '\u25CB', failed: '\u2717' };
      return map[status] || '\u25CB';
    },
  };
}
