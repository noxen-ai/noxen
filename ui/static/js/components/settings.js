/**
 * Noxen — Settings Tab Component
 */
function settingsComponent() {
  return {
    settings: {
      llm: { mode: 'single', providers: {} },
      mysql: {},
      board: {},
      notifications: {},
      research: {},
      multitenant: false,
    },
    testResults: {},

    async init() {
      await this.loadSettings();
    },

    async loadSettings() {
      try {
        const data = await NoxenAPI.getSettings();
        // Merge loaded settings
        if (data) {
          this.settings.llm = {
            mode: data.board_mode ? 'board' : 'single',
            providers: {},
          };
          this.settings.mysql = data.mysql || {};
          this.settings.multitenant = data.multitenant_enabled || false;
        }
      } catch {}

      // Load providers separately
      try {
        const providers = await NoxenAPI.getProviders();
        if (providers) this.settings.llm.providers = providers;
      } catch {}
    },

    async saveSettings(data) {
      try {
        await NoxenAPI.saveSettings(data);
        this.$root.addToast('Settings saved', 'success');
      } catch (e) {
        this.$root.addToast(`Save failed: ${e.message}`, 'error');
      }
    },

    async saveProvider(name, apiKey, model) {
      if (!apiKey || apiKey === '********') return;
      try {
        await NoxenAPI.saveSettings({ [`${name}_api_key`]: apiKey });
        this.testResults[name] = 'Saved';
        this.$root.addToast(`${name} key saved`, 'success');
      } catch (e) {
        this.$root.addToast(`Save failed: ${e.message}`, 'error');
      }
    },

    async testProvider(name) {
      this.testResults[name] = 'Testing...';
      try {
        const res = await NoxenAPI.post('/api/orchestrator/chat', {
          message: 'test', provider: name, stream: false,
        });
        this.testResults[name] = 'OK';
      } catch {
        this.testResults[name] = 'Failed';
      }
    },
  };
}
