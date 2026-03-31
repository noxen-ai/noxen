/**
 * Noxen — Notifications Tab Component
 */
function notificationsComponent() {
  return {
    channels: [],
    pendingApprovals: [],
    testingChannel: null,

    async init() {
      await Promise.allSettled([
        this.loadChannels(),
        this.loadApprovals(),
      ]);
    },

    async loadChannels() {
      try {
        const data = await NoxenAPI.notificationChannels();
        this.channels = data?.channels || data || [];
      } catch { this.channels = []; }
    },

    async loadApprovals() {
      try {
        const data = await NoxenAPI.notificationApprovals();
        this.pendingApprovals = data?.approvals || data || [];
      } catch { this.pendingApprovals = []; }
    },

    async testChannel(name) {
      this.testingChannel = name;
      try {
        await NoxenAPI.notificationTest(name);
        this.$root.addToast(`Test sent to ${name}`, 'success');
      } catch (e) {
        this.$root.addToast(`Test failed: ${e.message}`, 'error');
      }
      this.testingChannel = null;
    },

    async approveRequest(approvalId) {
      try {
        await NoxenAPI.notificationApprove(approvalId, '');
        this.$root.addToast('Approved', 'success');
        await this.loadApprovals();
      } catch (e) {
        this.$root.addToast(`Approve failed: ${e.message}`, 'error');
      }
    },

    async rejectRequest(approvalId) {
      try {
        await NoxenAPI.notificationReject(approvalId, 'Rejected from dashboard');
        this.$root.addToast('Rejected', 'info');
        await this.loadApprovals();
      } catch (e) {
        this.$root.addToast(`Reject failed: ${e.message}`, 'error');
      }
    },

    channelIcon(name) {
      const map = { telegram: '\uD83D\uDCE8', slack: '\uD83D\uDCAC', google_chat: '\uD83D\uDDE8\uFE0F', email: '\u2709\uFE0F' };
      return map[name] || '\uD83D\uDD14';
    },
  };
}
