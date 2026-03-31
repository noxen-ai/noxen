# Dashboard Analysis — Step 9.0

**Data:** 2026-03-30

## Current State

### Files
- `ui/templates/dashboard.html` — 960 lines (HTML shell + all tab markup)
- `ui/static/js/dashboard.js` — 37,592 bytes (tabs, overview, repos, agents, bridge, terminal)
- `ui/static/js/chat.js` — 11,028 bytes (chat SSE streaming, conversations)
- `ui/static/js/spider.js` — 18,359 bytes (spider analysis, engine controls)
- `ui/static/js/settings.js` — 13,624 bytes (LLM providers, MySQL config)

### Existing Tabs (8)
1. **Overview** — KB count, skills count, agents count, LLM info, DB status, Qdrant stats, console log
2. **Chat** — SSE streaming chat, Neural Engine sidebar, Spider Analysis sidebar, conversations, prompt templates
3. **Skills** — Install from GitHub, repo grid, plugin scan
4. **Agents** — Agent grid by group, filtering by plugin/group
5. **Settings** — LLM providers (7: Ollama, Gemini, Claude, OpenAI, Grok, Mercury, Qwen), board mode, MySQL
6. **Bridge** — Bridge API manifest, test live
7. **Terminal** — Multi-tab xterm.js terminal via WebSocket
8. **Guide** — Onboarding 4-step guide, API cheat sheet

### Architecture
- Vanilla JS with global functions (no modules)
- Tailwind CSS via CDN
- Tab switching via `showTab()` function toggling `.hidden` class
- SSE streaming for chat via fetch + ReadableStream
- xterm.js for terminal (WebSocket)
- Jinja2 template variables for initial settings values

## What to Add for v0.3.0

### New Tabs
1. **Research** (Phase 3) — trigger research pipeline, pending skills, research log
2. **Skill Pool** (Phase 6) — knowledge skills with confidence scores, approve/reject, search
3. **Board** (Phase 2) — board deliberations, review history
4. **Execution** (Phase 4) — execution engine v2 with approval gate, goal progress
5. **Notifications** (Phase 5) — channel status, pending approvals, test buttons
6. **Admin** (Phase 8) — tenant CRUD, API key management (admin only)

### Enhancements to Existing
- **Overview**: Add events live feed, skill pool stats, engine status
- **Chat**: Keep SSE streaming (working well), add project selector
- **Settings**: Add board config, notification channels, research config, multitenant toggle
- **Header**: Add tenant name, provider status, version v0.8.0

### Removed/Deprecated
- **Bridge** tab — deprecated (Execution Engine replaces it)
- **Terminal** tab — keep but move to secondary
- **Guide** tab — collapse into a help modal or keep as last tab

## Migration Strategy

Replace the monolithic dashboard.html with:
1. **AlpineJS** x-data components for reactive state
2. **api.js** — centralized API client with auth headers
3. **sse.js** — SSE event manager with handlers
4. **app.js** — AlpineJS root component with tab routing
5. **One JS file per tab** — component pattern

### Tab Layout (9 tabs + admin)
sidebar navigation, 9 primary tabs:
Overview | Chat | Research | Skills | Board | Execution | Notifications | Settings | Admin

### Design
- Dark theme (gray-950 bg, same as current)
- Sidebar navigation (vertical) instead of horizontal tabs
- Indigo/violet accent (same as current)
- Cards with glow effect (same as current)
- Real-time SSE updates across all tabs

## Risk Assessment
- Chat SSE streaming must be preserved exactly — it works well
- Terminal xterm.js integration is complex — keep in settings or separate
- Jinja2 template variables ({{ settings.x }}) need to be replaced with API calls
- No framework dependencies to add — AlpineJS CDN is lightweight
