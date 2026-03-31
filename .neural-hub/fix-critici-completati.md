# Fix Critici Completati

**Data:** 2026-03-30
**Versione:** v0.8.0-alpha
**Test prima:** 1108
**Test dopo:** 1162 (tutti passano)
**Test nuovi:** 54

## Fix Completati

### FIX 1 — Bootstrap Health Checks (19 test)

**File creati:**
- `core/bootstrap.py` — `NeuralHubBootstrap` con 8 health checks

**File modificati:**
- `main.py` — integrazione bootstrap nel lifespan
- `api/routes/health.py` — `/api/health` include bootstrap result

**Checks obbligatori (required=True):**
- `qdrant` — Qdrant raggiungibile
- `embedding` — FastEmbed funzionante
- `data_dirs` — Directory dati scrivibili
- `default_tenant` — Tenant default esistente

**Checks opzionali (required=False):**
- `claude_cli` — Claude Code CLI nel PATH
- `github_token` — GitHub token configurato
- `exa_api_key` — Exa API key configurata
- `firecrawl_key` — Firecrawl API key configurata

**Health endpoint response:**
```json
{
  "status": "ok | degraded | error",
  "version": "0.3.0",
  "bootstrap": {
    "success": true,
    "checks": [...],
    "errors": [],
    "warnings": [...]
  }
}
```

### FIX 2 — Dependency Injection Container (19 test)

**File creati:**
- `core/container.py` — `NeuralHubContainer` con 8 layer

**File modificati:**
- `main.py` — refactorato per usare container

**Layer di inizializzazione:**
```
Layer 0: Config (settings)
Layer 1: Base managers (skill_manager, project_manager, ingestor, plugin_composer)
Layer 2: Providers (llm_provider, knowledge_base, skill_router, event_router)
Layer 3: Research (github_client, repo_analyzer, web_researcher, research_agent)
Layer 4: Notification (notification_engine + 4 channels)
Layer 5: Tenant (tenant_repository)
Layer 6: Skill System v2 (skill_repository, board_reviewer, updater, usage_tracker)
Layer 7: Context & Orchestration (context_gatherer, orchestrator)
Layer 8: Async (qdrant, embedding_provider, bootstrap) — in initialize_async()
```

**Backward compatibility:** Module-level aliases mantengono compatibilita'
con tutto il codice e test esistenti.

### FIX 3 — Claude Code CLI Check (4 test)

**File modificati:**
- `core/execution/claude_executor.py` — aggiunto `check_availability()` e pre-check in `execute()`

**Comportamento:**
- `check_availability()` verifica `shutil.which("claude")`
- `execute()` ritorna errore immediato se CLI non disponibile
- Messaggio errore include comando install: `npm install -g @anthropic-ai/claude-code`

### FIX 4 — Allineamento "default" vs "global" (12 test)

**Costanti definite:**
- `NeuralQdrantClient.DEFAULT_TENANT = "default"` — dati privati tenant on-premise
- `NeuralQdrantClient.GLOBAL_TENANT = "global"` — skill condivise tra tenant
- `SkillRepository.GLOBAL_TENANT = "global"` — (gia' esistente)
- `TenantRepository.DEFAULT_TENANT_ID = "default"` — (gia' esistente)
- `lifecycle.GLOBAL_SKILLS_TENANT = "global"` — costante per dataclass default

**File corretti (hardcoded -> costante):**
- `core/knowledge_base.py` — `"default"` -> `NeuralQdrantClient.DEFAULT_TENANT`
- `core/ingestor.py` — `"default"` -> `NeuralQdrantClient.DEFAULT_TENANT`
- `core/project_manager.py` — `"default"` -> `NeuralQdrantClient.DEFAULT_TENANT`
- `core/event_router.py` — `"default"` -> `NeuralQdrantClient.DEFAULT_TENANT`
- `core/skills/lifecycle.py` — `"global"` -> `GLOBAL_SKILLS_TENANT`
- `core/skills/updater.py` — `"global"` -> `SkillRepository.GLOBAL_TENANT`
- `core/skills/usage_tracker.py` — `"global"` -> `SkillRepository.GLOBAL_TENANT`
- `api/routes/admin.py` — `"default"` -> `TenantRepository.DEFAULT_TENANT_ID`

**Regola semantica:**
- `DEFAULT_TENANT ("default")`: dati privati tenant on-premise (progetti, findings, events)
- `GLOBAL_TENANT ("global")`: skill condivise tra tutti i tenant

**Grep test:** verifica che nessun file core usa stringhe hardcoded per tenant_id.

## Output Bootstrap su questa macchina

```
OK   qdrant: Qdrant raggiungibile (se Docker attivo)
OK   embedding: FastEmbed funzionante
OK   data_dirs: Directory dati OK
OK   default_tenant: Tenant default: default
WARN claude_cli: Claude Code CLI non trovato [OPTIONAL]
WARN github_token: GitHub token non configurato [OPTIONAL]
WARN exa_api_key: Exa API key non configurata [OPTIONAL]
WARN firecrawl_key: Firecrawl API key non configurata [OPTIONAL]
```

## Warning Rilevati
- Nessun warning bloccante
- 4 checks opzionali missing (claude_cli, github_token, exa_api_key, firecrawl_key) — attesi su dev machine senza config
- DeprecationWarning su `core.neural_engine` — legacy, non bloccante
- DeprecationWarning su `TemplateResponse` — Starlette API change, non bloccante

## Conferma
Il sistema e' pronto per il test su progetto reale.
Tutti i 1162 test passano. I fix critici garantiscono:
1. Bootstrap chiaro con health checks espliciti
2. Dipendenze ordinate e documentate nel container
3. Claude CLI verificato prima dell'uso
4. Nessuna ambiguita' su tenant_id "default" vs "global"
