# Phase 2 — Completata

**Data**: 2026-03-30
**Versione**: v0.4.0-alpha (Phase 2 — Orchestrator Refactor)

## Checklist

- [x] **Step 2.0** — Analysis pre-refactor: lettura orchestrator.py, mapping dipendenze, scrittura orchestrator-deps.md
- [x] **Step 2.1** — ContextGatherer estratto da orchestrator (_gather_context + _build_system_prompt) + 20 test
- [x] **Step 2.2** — SkillRouter estratto da orchestrator (SKILL_ROUTING + _route_skills + semantic_route) + 18 test
- [x] **Step 2.3** — EventRouter creato (emit, persist Qdrant, buffer circolare, stats) + 19 test
- [x] **Step 2.4** — Orchestrator refactored per usare ContextGatherer, SkillRouter, EventRouter + main.py aggiornato
- [x] **Step 2.5** — Board LLM ASYNC/SYNC modes (board_mode="sync"|"async", fire-and-forget) + 7 test
- [x] **Step 2.6** — Model routing per task type (MODEL_ROUTING map, route_query, _resolve_provider_for_task) + 8 test

## Test Results

```
260 passed in 2.21s
```

### Test Count: Prima vs Dopo
| Momento | Test |
|---------|------|
| Fase 1 completata | 188 |
| Fase 2 completata | 260 |
| **Nuovi test Fase 2** | **72** |

### Test Files Nuovi (3)
| File | Tests | Covers |
|------|-------|--------|
| test_context_gatherer.py | 20 | core/context_gatherer.py (NEW) |
| test_skill_router.py | 18 | core/skill_router.py (NEW) |
| test_event_router.py | 19 | core/event_router.py (NEW) |

### Test Files Modificati (1)
| File | Tests Before | Tests After | Delta |
|------|-------------|-------------|-------|
| test_llm_provider.py | 20 | 35 | +15 (board_mode + model routing) |

## Componenti Creati

### core/context_gatherer.py (NEW)
- `ContextGatherer` class estratta da Orchestrator
- `gather()` async — raccoglie KB, RAG, DB, Skills context
- `_build_system_prompt()` — costruisce system prompt unificato
- Dipendenze iniettate: knowledge_base, project_manager, skill_router
- Attributi settabili: db, db_schema, ecosystem, initialized

### core/skill_router.py (NEW)
- `SkillRouter` class estratta da Orchestrator
- `route()` — keyword matching per categoria (security, api, db, etc.)
- `semantic_route()` async — ricerca semantica via Qdrant "skills" collection
- `refresh_cache()` — ricarica skill dal plugin_composer
- `SKILL_ROUTING` dict — mappa categorie → keyword

### core/event_router.py (NEW)
- `EventRouter` class — router/logger eventi
- `emit()` async — emette evento con tipo, data, source
- `_persist_event()` — salva su Qdrant "events" collection (best-effort)
- `get_recent()` — buffer circolare in-memory (ultimi 100 eventi)
- `get_stats()` — conteggi per tipo
- `EVENT_TYPES` set — query, init, spider, engine, db, skill, error, system

### core/orchestrator.py (REFACTORED)
- Rimosso: `_gather_context()` (80 righe) → delegato a ContextGatherer
- Rimosso: `_build_system_prompt()` (27 righe) → dentro ContextGatherer (kept as fallback)
- Rimosso: `_route_skills()` (24 righe) → delegato a SkillRouter
- Rimosso: `SKILL_ROUTING` dict (10 righe) → dentro SkillRouter
- Aggiunto: `context_gatherer`, `skill_router`, `event_router` come dipendenze
- Aggiunto: `_sync_context_gatherer()` — sincronizza stato post-init
- Aggiunto: `event_router.emit()` in init_project(), query(), db_query()
- **Interfaccia pubblica INVARIATA** — zero breaking change per routes

### core/llm_provider.py (ENHANCED)
- `BoardResponse.board_mode` field — "sync" o "async"
- `board_query(board_mode=)` parameter — sceglie modalita' sync/async
- `_board_query_sync()` — comportamento originale, aspetta tutti i provider
- `_board_query_async()` — fire-and-forget, ritorna primo risultato
- `_complete_board_async()` — raccoglie risultati rimanenti in background
- `MODEL_ROUTING` dict — mappa task_type → lista provider preferiti
- `route_query(task_type=)` — query con routing automatico
- `_resolve_provider_for_task()` — seleziona provider migliore per task

## Files Created
- `.neural-hub/orchestrator-deps.md` — Dependency map pre-refactor
- `core/context_gatherer.py` — Context gathering estratto
- `core/skill_router.py` — Skill routing estratto + semantic search
- `core/event_router.py` — Event bus leggero
- `tests/test_context_gatherer.py` — 20 test
- `tests/test_skill_router.py` — 18 test
- `tests/test_event_router.py` — 19 test

## Files Modified
- `core/orchestrator.py` — Refactored, 503→~300 righe di logica propria (il resto delegato)
- `core/llm_provider.py` — Board async/sync + model routing
- `core/__init__.py` — Aggiunto export ContextGatherer, SkillRouter, EventRouter
- `main.py` — Crea e inietta i nuovi componenti nell'Orchestrator
- `tests/test_llm_provider.py` — +15 test per board_mode e model routing

## Architettura Post-Refactor

```
                    ┌─────────────────┐
                    │   API Routes    │
                    │ (orchestrator)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Orchestrator   │ ← interfaccia invariata
                    │  (coordinatore) │
                    └──┬───┬───┬───┬──┘
                       │   │   │   │
            ┌──────────┘   │   │   └──────────┐
            │              │   │              │
   ┌────────▼──────┐  ┌───▼───▼───┐  ┌───────▼──────┐
   │ContextGatherer│  │SkillRouter│  │ EventRouter  │
   │ (KB+RAG+DB)   │  │(kw+Qdrant)│  │(Qdrant logs) │
   └───────────────┘  └───────────┘  └──────────────┘
            │                                  │
   ┌────────▼──────────────────────────────────▼──┐
   │              Qdrant (7 collections)          │
   │  projects skills findings cycles events      │
   │  approvals codebase                          │
   └──────────────────────────────────────────────┘
```

## MODEL_ROUTING Map
| Task Type | Provider Preference |
|-----------|-------------------|
| routing | gemini → ollama |
| analysis | claude → gemini → openai |
| architecture | claude → openai → gemini |
| code | claude → openai → qwen |
| security | claude → openai → gemini |
| synthesis | gemini → claude → openai |
| quick | gemini → ollama → grok |
| creative | claude → openai → gemini |

## Board Modes
| Mode | Comportamento |
|------|--------------|
| sync (default) | Aspetta tutti i provider, poi sintetizza |
| async | Ritorna il primo provider, lancia sintesi in background |

## Zero Breaking Changes
- Tutti i 188 test della Fase 1 passano senza modifiche
- `api/routes/orchestrator.py` non modificato (interfaccia Orchestrator invariata)
- `core/spider.py` non modificato (usa orch.llm e kb come prima)
- `core/neural_engine.py` non modificato (usa orch.llm e kb come prima)

## Note per la Fase 3

La codebase e' ora pronta per la Fase 3: Dashboard Refactor.
- Orchestrator decomposto in 4 componenti: Orchestrator, ContextGatherer, SkillRouter, EventRouter
- EventRouter pronto per alimentare dashboard real-time via SSE
- Model routing pronto per UI di selezione task-type
- Board async pronto per UX non-bloccante
- 260 test passanti
- Zero regressioni
