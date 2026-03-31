# Orchestrator Dependency Map — Pre-Refactor Analysis

**Data**: 2026-03-30
**File**: `core/orchestrator.py` (503 righe)
**Obiettivo**: Mappatura completa prima del refactor Phase 2

---

## 1. Dipendenze IN USCITA (Orchestrator usa)

| Modulo | Import | Metodi/Attributi usati | Dove |
|--------|--------|----------------------|------|
| `core.auto_discovery` | `AutoDiscovery, EcosystemMap` | `AutoDiscovery(root)`, `.scan()`, `.save_map()` | `init_project()` |
| `core.claude_skill_parser` | `parse_plugin_repo, ClaudeSkill` | (importato ma non usato direttamente) | top-level |
| `core.db_connector` | `DBConnector, SchemaInfo` | `.connect()`, `.get_schema()`, `.query()`, `.schema_to_text()` | `init_project()`, `_gather_context()`, `db_query()` |
| `core.llm_provider` | `LLMProvider, LLMResponse, BoardResponse` | `.query()`, `.stream_query()`, `.board_query()`, `.available_providers` | `query()`, `stream_query()`, `init_project()` |
| `core.knowledge_base` | (via constructor) | `.search()` (async) | `_gather_context()` |
| `core.project_manager` | (via constructor) | `.register()`, `.search()`, `.projects` | `init_project()`, `_gather_context()` |
| `core.ingestor` | (via constructor) | `.start_indexing()` | `init_project()` |
| `core.plugin_composer` | (via constructor) | `.scan_all()`, `.get_all_skills()` | `init_project()` |
| `config.settings` | `settings` | `.llm_mode`, `.active_provider`, `.mysql_*`, `.data_dir` | multipli |

## 2. Dipendenze IN ENTRATA (chi usa Orchestrator)

### `api/routes/orchestrator.py` (380 righe)
| Endpoint | Metodo Orchestrator | Attributi letti |
|----------|-------------------|-----------------|
| `POST /api/orchestrator/chat` | `orch.stream_query()`, `orch.query()` | — |
| `POST /api/orchestrator/query` | `orch.query()` | — |
| `POST /api/orchestrator/init` | `orch.init_project()` | — |
| `GET /api/orchestrator/status` | — | `orch.state.to_dict()`, `orch.knowledge_base.get_stats()` |
| `POST /api/orchestrator/db-query` | `orch.db_query()` | `orch.state.db_connected` |
| `POST /api/orchestrator/analyze` | `orch.analyze_and_instruct()` | — |
| `POST /api/orchestrator/spider` | — | `orch` (passato a SpiderAnalysis), `orch.knowledge_base` |
| `POST /api/orchestrator/engine/start` | — | `orch` (passato a NeuralEngine), `orch.knowledge_base` |

### `core/spider.py`
- `SpiderAnalysis(orchestrator, knowledge_base)` — riceve orchestrator come dipendenza
- Usa: `self.orchestrator.llm` (per stream_query)
- Usa: `self.kb.search()` (async)

### `core/neural_engine.py`
- `NeuralEngine(orchestrator, knowledge_base)` — riceve orchestrator come dipendenza
- Usa: `self.orchestrator.llm` (per stream_query)
- Usa: `self.kb.search()` (async)
- Usa: `self.orchestrator` per accedere a project_name via state

### `main.py`
- Crea: `Orchestrator(llm_provider, ingestor, project_manager, plugin_composer, knowledge_base)`
- Passa a: `orchestrator.init_router(orch, llm_provider)`

## 3. Metodi Pubblici dell'Orchestrator

| Metodo | Signature | Usato da |
|--------|----------|----------|
| `init_project()` | `async (project_path: str) -> dict` | routes/orchestrator.py |
| `query()` | `async (question, service, use_db, mode) -> dict` | routes/orchestrator.py, self.analyze_and_instruct() |
| `stream_query()` | `async gen (messages, service, use_db) -> str` | routes/orchestrator.py |
| `db_query()` | `async (sql: str) -> list[dict]` | routes/orchestrator.py |
| `analyze_and_instruct()` | `async (task: str) -> dict` | routes/orchestrator.py |

## 4. Attributi Pubblici dell'Orchestrator

| Attributo | Tipo | Letto da |
|-----------|------|----------|
| `state` | `OrchestratorState` | routes/orchestrator.py (`.to_dict()`, `.db_connected`) |
| `knowledge_base` | `KnowledgeBase` | routes/orchestrator.py, SpiderAnalysis, NeuralEngine |
| `db` | `DBConnector \| None` | routes/orchestrator.py (via `db_query()`) |
| `llm` | `LLMProvider` | SpiderAnalysis, NeuralEngine |
| `project_manager` | `ProjectManager` | internal |
| `ingestor` | `Ingestor` | internal |
| `plugin_composer` | `PluginComposer` | internal |
| `discovery` | `AutoDiscovery \| None` | internal |

## 5. Metodi Privati da Estrarre

| Metodo | Righe | Destinazione Phase 2 |
|--------|-------|---------------------|
| `_gather_context()` | 223-302 (80 righe) | → `core/context_gatherer.py` (Step 2.1) |
| `_route_skills()` | 479-502 (24 righe) | → `core/skill_router.py` (Step 2.2) |
| `_build_system_prompt()` | 451-477 (27 righe) | → `core/context_gatherer.py` (Step 2.1) |
| `SKILL_ROUTING` dict | 68-77 (10 righe) | → `core/skill_router.py` (Step 2.2) |

## 6. Piano di Estrazione

### Step 2.1 — ContextGatherer
Estrae da Orchestrator:
- `_gather_context()` → `ContextGatherer.gather()`
- `_build_system_prompt()` → `ContextGatherer._build_system_prompt()`
- Dipendenze: knowledge_base, project_manager, db, state, skill_router

### Step 2.2 — SkillRouter
Estrae da Orchestrator:
- `SKILL_ROUTING` → dentro SkillRouter
- `_route_skills()` → `SkillRouter.route()` (keyword) + `SkillRouter.semantic_route()` (Qdrant)
- `_skills_cache` → `SkillRouter._cache`
- Dipendenze: plugin_composer (per refresh cache), Qdrant skills collection

### Step 2.3 — EventRouter
Nuovo componente:
- Riceve eventi, li logga su Qdrant collection "events"
- Routing leggero: decide dove mandare una richiesta senza LLM
- Dipendenze: Qdrant events collection

### Step 2.4 — Orchestrator Refactored
Dopo estrazione, l'Orchestrator diventa:
- `__init__()` riceve: llm, context_gatherer, skill_router, event_router, (+ legacy deps)
- `query()` e `stream_query()` delegano a context_gatherer.gather()
- `_route_skills()` eliminato → usa skill_router
- `_gather_context()` eliminato → usa context_gatherer
- `_build_system_prompt()` eliminato → dentro context_gatherer
- **Interfaccia pubblica INVARIATA** → zero breaking change per routes

## 7. Rischi Identificati

1. **SpiderAnalysis e NeuralEngine accedono a `orch.llm` e `orch.knowledge_base` direttamente** — durante il refactor questi attributi devono restare accessibili
2. **`_gather_context()` accede a `self.state`** — il ContextGatherer avrà bisogno di un riferimento allo state o riceverà i dati necessari come parametri
3. **`analyze_and_instruct()` chiama `self.query()` internamente** — la catena deve restare intatta
4. **`init_project()` modifica `self._skills_cache`** — deve aggiornare anche SkillRouter
5. **Import circolare potenziale** — ContextGatherer usa SkillRouter, Orchestrator usa entrambi → iniettare via constructor, non import diretto
