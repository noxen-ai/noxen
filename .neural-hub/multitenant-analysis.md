# Multitenant Analysis — Phase 8 Pre-Development

**Data**: 2026-03-30

## 1. Punti dove tenant_id E' GIA' PRESENTE

### Fully implemented (Phase 6 Skill System)
| File | Pattern | Stato |
|------|---------|-------|
| `core/skills/lifecycle.py` | `tenant_id: str = "global"` nel dataclass Skill | OK |
| `core/skills/repository.py` | `GLOBAL_TENANT = "global"`, search two-tier (tenant -> global) | OK |
| `core/skills/updater.py` | `tenant_id` param in `check_degraded_skills()` | OK |
| `core/skills/usage_tracker.py` | `tenant_id` param in `get_usage_analytics()` | OK |
| `api/routes/skills_v2.py` | Query param `tenant_id="global"` su tutti gli endpoint | OK |

## 2. Punti dove tenant_id E' HARDCODED "default"

| File | Riga | Problema |
|------|------|----------|
| `core/knowledge_base.py` | ~358 | `"tenant_id": "default"` hardcoded nel payload Qdrant |
| `core/ingestor.py` | ~260 | `"tenant_id": "default"` hardcoded nel payload |
| `core/project_manager.py` | ~265 | `"tenant_id": "default"` hardcoded nel payload |
| `core/event_router.py` | ~113 | `"tenant_id": "default"` hardcoded nel payload |

Questi vanno parametrizzati: accettare `tenant_id` come argomento,
default a `"global"` per retrocompatibilita.

## 3. Punti dove tenant_id MANCA completamente

| File | Cosa manca |
|------|------------|
| `api/routes/orchestrator.py` | Nessun tenant context, delega a core senza tenant_id |
| `api/routes/research.py` | Nessun tenant context |
| `api/routes/projects.py` | Nessun tenant context |
| `api/routes/knowledge.py` | Nessun tenant context |
| `api/routes/notifications.py` | Nessun tenant context |
| `api/middleware/` | `__init__.py` vuoto, nessun middleware auth |
| `core/llm_provider.py` | Config globale, nessun per-tenant |
| `core/notifications/engine.py` | Canali globali, nessun per-tenant |

## 4. Layer da toccare

### A. API (Auth Middleware)
- Creare `core/tenants/auth.py` con FastAPI dependency
- Strategie: Bearer API key (SaaS) / X-Tenant-ID (on-premise) / default
- Setting `multitenant_enabled: bool = False` in config

### B. Qdrant (Namespace Isolation)
- `core/qdrant_client.py`: aggiungere `search_with_tenant()`, `upsert_with_tenant()`
- Tutte le collection usano payload filter `tenant_id`
- Skill globali: `tenant_id = "global"` (condivise)
- Dati progetto: `tenant_id = <tenant_id>` (isolati)

### C. Settings (Per-Tenant Config)
- `config/settings.py`: aggiungere `multitenant_enabled`, `admin_api_key`
- `core/tenants/model.py`: TenantConfig con LLM keys e notification channels
- Per-tenant LLM provider override

### D. Notification Engine (Per-Tenant Channels)
- Factory method `NotificationEngine.for_tenant(tenant_config)`
- Canali configurati dal TenantConfig, non da settings globali

## 5. Decisioni architetturali

- **SQLite per tenant CRUD** (non Qdrant): dati strutturati, ACID, query precise
- **Qdrant per dati tenant** (skill, findings, events): semantic search, payload filter
- **Default tenant "default"** per on-premise: ENTERPRISE plan, sempre ACTIVE
- **Retrocompatibilita**: multitenant_enabled=False = nessuna auth richiesta
- **API key hashing**: SHA-256 (non bcrypt per semplicita async)
- **Inconsistenza "default" vs "global"**: i file legacy usano "default",
  il skill system usa "global". Unificare a "global" dove possibile,
  ma il tenant on-premise si chiamera "default" (ID).
