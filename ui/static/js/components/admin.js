/**
 * Noxen — Admin Tab Component
 */
function adminComponent() {
  return {
    isAdmin: true,  // On-premise default = admin
    tenants: [],
    selectedTenant: null,
    generatedKey: '',
    newApiKeyName: '',
    newTenant: { name: '', slug: '', plan: 'pro' },
    license: null,
    upgradeForm: { plan: 'team', purchase_reference: '', notes: '' },
    upgradeResult: null,

    async init() {
      await this.loadTenants();
    },

    async loadTenants() {
      try {
        const data = await NoxenAPI.adminListTenants();
        this.tenants = data?.tenants || data || [];
      } catch (e) {
        if (e.message.includes('403') || e.message.includes('401')) {
          this.isAdmin = false;
        }
        this.tenants = [];
      }
    },

    async createTenant() {
      if (!this.newTenant.name || !this.newTenant.slug) return;
      try {
        const result = await NoxenAPI.adminCreateTenant(this.newTenant);
        this.$root.addToast(`Tenant "${this.newTenant.name}" created`, 'success');
        this.newTenant = { name: '', slug: '', plan: 'pro' };
        await this.loadTenants();
      } catch (e) {
        this.$root.addToast(`Create failed: ${e.message}`, 'error');
      }
    },

    async deleteTenant(id) {
      if (!confirm('Delete this tenant? This cannot be undone.')) return;
      try {
        await NoxenAPI.adminDeleteTenant(id);
        this.$root.addToast('Tenant deleted', 'info');
        await this.loadTenants();
      } catch (e) {
        this.$root.addToast(`Delete failed: ${e.message}`, 'error');
      }
    },

    async createApiKey(tenantId) {
      if (!this.newApiKeyName) return;
      try {
        const result = await NoxenAPI.adminCreateApiKey(tenantId, this.newApiKeyName);
        this.generatedKey = result?.api_key || result?.key || '';
        this.newApiKeyName = '';
        this.$root.addToast('API key generated', 'success');
      } catch (e) {
        this.$root.addToast(`Key generation failed: ${e.message}`, 'error');
      }
    },

    async loadLicense() {
      if (!this.selectedTenant) return;
      try {
        this.license = await NoxenAPI.get('/api/admin/tenants/' + this.selectedTenant.id + '/license');
      } catch(e) { this.license = null; }
    },

    async upgradeLicense() {
      if (!this.selectedTenant) return;
      try {
        this.license = await NoxenAPI.post('/api/admin/tenants/' + this.selectedTenant.id + '/license/upgrade', this.upgradeForm);
        this.upgradeResult = 'OK';
        this.$root.addToast('License upgraded', 'success');
      } catch(e) {
        this.upgradeResult = 'Errore: ' + e.message;
        this.$root.addToast('Upgrade failed: ' + e.message, 'error');
      }
    },

    planBadge(plan) {
      const map = {
        free: 'bg-gray-800 text-gray-400',
        pro: 'bg-indigo-900 text-indigo-300',
        enterprise: 'bg-purple-900 text-purple-300',
      };
      return map[plan] || 'bg-gray-800 text-gray-400';
    },

    statusBadge(status) {
      const map = {
        active: 'bg-green-900 text-green-300',
        suspended: 'bg-red-900 text-red-300',
        trial: 'bg-yellow-900 text-yellow-300',
      };
      return map[status] || 'bg-gray-800 text-gray-400';
    },
  };
}
