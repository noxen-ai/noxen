/**
 * Noxen — SSE Event Manager
 * Polls /api/events/recent and dispatches to registered handlers.
 */

const NoxenSSE = {
  _handlers: {},
  _interval: null,
  _lastId: null,
  _polling: false,

  on(eventType, callback) {
    if (!this._handlers[eventType]) this._handlers[eventType] = [];
    this._handlers[eventType].push(callback);
  },

  off(eventType, callback) {
    if (!this._handlers[eventType]) return;
    this._handlers[eventType] = this._handlers[eventType].filter(h => h !== callback);
  },

  emit(eventType, event) {
    const handlers = this._handlers[eventType] || [];
    handlers.forEach(h => {
      try { h(event); } catch (e) { console.error('[SSE] Handler error:', e); }
    });
    const wildcard = this._handlers['*'] || [];
    wildcard.forEach(h => {
      try { h(event); } catch (e) { console.error('[SSE] Wildcard handler error:', e); }
    });
  },

  start(intervalMs = 5000) {
    if (this._interval) return;
    this._poll();
    this._interval = setInterval(() => this._poll(), intervalMs);
  },

  stop() {
    if (this._interval) {
      clearInterval(this._interval);
      this._interval = null;
    }
  },

  async _poll() {
    if (this._polling) return;
    this._polling = true;
    try {
      const events = await NoxenAPI.recentEvents(50);
      if (Array.isArray(events)) {
        for (const event of events) {
          const eventId = event.id || event.timestamp;
          if (this._lastId && eventId <= this._lastId) continue;
          this.emit(event.event_type || event.type, event);
        }
        if (events.length > 0) {
          this._lastId = events[events.length - 1].id || events[events.length - 1].timestamp;
        }
      }
    } catch {
      // silent — server may be offline
    }
    this._polling = false;
  },
};
