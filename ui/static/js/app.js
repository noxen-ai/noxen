/**
 * Noxen SPA — Root AlpineJS component.
 * State management, tab routing, global notifications.
 */

function noxenApp() {
  return {
    // ── Tab state ────────────────────────────────
    activeTab: 'overview',
    tabs: [
      { id: 'overview',      label: 'Overview',       icon: '&#9673;' },
      { id: 'chat',          label: 'Chat',           icon: '&#9993;' },
      { id: 'research',      label: 'Research',       icon: '&#9881;' },
      { id: 'skills',        label: 'Skills',         icon: '&#9830;' },
      { id: 'board',         label: 'Board',          icon: '&#9878;' },
      { id: 'execution',     label: 'Execution',      icon: '&#9654;' },
      { id: 'notifications', label: 'Notifications',  icon: '&#9888;' },
      { id: 'settings',      label: 'Settings',       icon: '&#9881;' },
      { id: 'admin',         label: 'Admin',          icon: '&#9733;' },
    ],

    // ── Server state ─────────────────────────────
    serverStatus: 'checking',
    activeProvider: '',
    projectName: '',
    isInitialized: false,
    version: 'v0.8.0',

    // ── Tenant state ─────────────────────────────
    tenantId: 'default',
    tenantName: 'Default',
    tenantPlan: 'enterprise',

    // ── License state ───────────────────────────
    licenseInfo: null,

    // ── UI notifications (toasts) ────────────────
    toasts: [],

    // ── Lifecycle ────────────────────────────────
    async init() {
      // Start SSE polling
      NoxenSSE.start();

      // Global SSE handlers
      NoxenSSE.on('session_complete', () => {
        this.addToast('Session completed', 'success');
      });
      NoxenSSE.on('awaiting_approval', () => {
        this.addToast('Plan awaiting approval', 'warning');
      });
      NoxenSSE.on('error', (e) => {
        this.addToast(e.data?.message || 'Error', 'error');
      });

      // Load initial status + license
      await Promise.allSettled([this.loadStatus(), this.loadLicense()]);

      // Refresh every 30s
      setInterval(() => this.loadStatus(), 30000);
    },

    async loadLicense() {
      try { this.licenseInfo = await NoxenAPI.get('/api/tenants/license'); } catch(e) {}
    },

    async loadStatus() {
      try {
        const data = await NoxenAPI.status();
        this.serverStatus = 'online';
        this.activeProvider = data.active_provider || '';
        this.projectName = data.project_name || '';
        this.isInitialized = data.initialized || false;
      } catch {
        this.serverStatus = 'offline';
      }
    },

    // ── Tab navigation ───────────────────────────
    setTab(tab) {
      this.activeTab = tab;
    },

    // ── Toast notifications ──────────────────────
    addToast(message, type = 'info') {
      const id = Date.now();
      this.toasts.push({ id, message, type });
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
      }, 5000);
    },

    toastColor(type) {
      const colors = {
        success: 'bg-green-900/90 border-green-700 text-green-300',
        warning: 'bg-yellow-900/90 border-yellow-700 text-yellow-300',
        error: 'bg-red-900/90 border-red-700 text-red-300',
        info: 'bg-indigo-900/90 border-indigo-700 text-indigo-300',
      };
      return colors[type] || colors.info;
    },

    // ── Status helpers ───────────────────────────
    get statusDotClass() {
      const map = {
        online: 'status-dot online',
        offline: 'status-dot offline',
        checking: 'status-dot checking',
      };
      return map[this.serverStatus] || 'status-dot checking';
    },

    get statusLabel() {
      const map = { online: 'Online', offline: 'Offline', checking: 'Connecting...' };
      return map[this.serverStatus] || 'Unknown';
    },
  };
}
