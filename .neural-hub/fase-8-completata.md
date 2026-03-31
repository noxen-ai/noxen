# Fase 8 Completata — Multitenant Layer

**Data:** 2026-03-30
**Versione:** v0.8.0-alpha
**Test totali:** 1058 (tutti passano)

## Step Completati

### 8.0 — Multitenant Analysis
- Mappatura tenant_id usage nel codebase
- Identificati 4 file con hardcoded "default"
- Analisi compatibilita' backward

### 8.1 — Tenant Model (`core/tenants/model.py`)
- `TenantPlan`: FREE, PRO, ENTERPRISE con limiti differenziati
- `TenantStatus`: ACTIVE, SUSPENDED, TRIAL
- `TenantLimits`: max_projects, max_sessions, sandbox_size, board_providers
- `TenantConfig`: LLM config, notification channels
- `Tenant`: entity completa con plan, config, stats, serialization
- 19 test

### 8.2 — Tenant Repository (`core/tenants/repository.py`)
- SQLite backend per CRUD tenant (ACID, structured)
- API key management con SHA-256 hashing
- `create_api_key()` genera `nh_` prefixed keys
- `ensure_default_tenant()` per on-premise mode
- Session tracking e monthly reset
- 20 test

### 8.3 — Auth Middleware (`core/tenants/auth.py`)
- `TenantContext` dataclass con tenant, tenant_id, is_admin
- `get_tenant_context()` FastAPI dependency
- On-premise: no auth, default tenant, is_admin=True
- SaaS: Bearer API key, X-Tenant-ID header fallback
- Admin key grants is_admin=True
- Suspended tenants get 403
- `require_admin()` dependency
- 10 test

### 8.4 — Qdrant Tenant Isolation (`core/qdrant_client.py`)
- `search_with_tenant()`: Filter should (tenant OR global) / must (tenant only)
- `upsert_with_tenant()`: auto-inject tenant_id in payload
- `delete_tenant_data()`: scroll + delete per collection, protects global
- MockQdrant per test con support must/should filters
- 9 test

### 8.5 — Route Tenant Context
- Updated 6 route files: skills_v2, orchestrator, research, projects, knowledge, notifications
- All tenant-scoped endpoints use `ctx: TenantContext = Depends(get_tenant_context)`
- Removed `tenant_id` query params, replaced with `ctx.tenant_id`
- Updated pre-existing tests with `override_tenant_auth()`
- 13 test dedicati + fix test esistenti

### 8.6 — Admin API (`api/routes/admin.py`)
- POST/GET/PATCH/DELETE `/api/admin/tenants/`
- API key creation (returns plaintext once) and revocation
- Usage stats with plan limits
- Session counter reset
- All endpoints require `require_admin`
- 23 test

### 8.7 — Per-Tenant LLM Config (`core/llm_provider.py`)
- `LLMProvider.for_tenant(tenant)` factory method
- Maps tenant config (provider, API key) to provider config
- Supports all 7 providers (ollama, gemini, claude, openai, grok, mercury, qwen)
- Falls back to global config when no tenant key
- 15 test

### 8.8 — Per-Tenant Notifications (`core/notifications/engine.py`)
- `NotificationEngine.for_tenant(tenant)` factory method
- Creates channels from TenantConfig (Telegram, Slack, Google Chat, Email)
- Handles partial config (skips unconfigured channels)
- 10 test

## Architettura Multitenant

```
On-Premise (default):
  multitenant_enabled=False
  -> No auth required
  -> Default tenant (ENTERPRISE plan, is_admin=True)
  -> All features available

SaaS:
  multitenant_enabled=True
  -> Bearer API key auth (nh_ prefix, SHA-256 hashed)
  -> X-Tenant-ID header fallback
  -> Admin API key for management
  -> Plan-based resource limits
  -> Per-tenant LLM and notification config
  -> Qdrant payload filtering for data isolation
```

## File Modificati/Creati

### Core
- `core/tenants/model.py` (NEW)
- `core/tenants/repository.py` (NEW)
- `core/tenants/auth.py` (NEW)
- `core/qdrant_client.py` (MODIFIED — tenant-aware operations)
- `core/llm_provider.py` (MODIFIED — for_tenant factory)
- `core/notifications/engine.py` (MODIFIED — for_tenant factory)
- `config/settings.py` (MODIFIED — multitenant_enabled, admin_api_key)

### API Routes
- `api/routes/admin.py` (NEW)
- `api/routes/skills_v2.py` (MODIFIED — tenant context)
- `api/routes/orchestrator.py` (MODIFIED — tenant context)
- `api/routes/research.py` (MODIFIED — tenant context)
- `api/routes/projects.py` (MODIFIED — tenant context)
- `api/routes/knowledge.py` (MODIFIED — tenant context)
- `api/routes/notifications.py` (MODIFIED — tenant context)
- `main.py` (MODIFIED — admin router, tenant repo, init_auth)

### Tests (119 nuovi test in Fase 8)
- `tests/tenants/test_model.py` (19)
- `tests/tenants/test_repository.py` (20)
- `tests/tenants/test_auth.py` (10)
- `tests/tenants/test_qdrant_isolation.py` (9)
- `tests/tenants/test_route_tenant_ctx.py` (13)
- `tests/tenants/test_admin_api.py` (23)
- `tests/tenants/test_per_tenant_llm.py` (15)
- `tests/tenants/test_per_tenant_notifications.py` (10)
