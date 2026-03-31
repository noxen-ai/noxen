# Engine Analysis — Step 4.0

**Data**: 2026-03-30
**Scopo**: Mappare `core/neural_engine.py` prima di costruire il nuovo Execution Engine.

---

## 1. Metodi pubblici di NeuralEngine

| Metodo | Tipo | Usato da | Descrizione |
|--------|------|----------|-------------|
| `__init__(orchestrator, knowledge_base)` | sync | `api/routes/orchestrator.py:224` | Riceve orchestrator (per `orch.llm`) e KB |
| `run(project_path)` | async generator | `api/routes/orchestrator.py:228` | Loop principale — yield dict SSE events |
| `request_stop()` | sync | `api/routes/orchestrator.py:241` | Graceful stop via `state.stop_requested` |
| `state: EngineState` | attributo | `api/routes/orchestrator.py:250-256` | Stato corrente (is_running, goals, etc.) |
| `goals: list[Goal]` | attributo | `api/routes/orchestrator.py:255` | Lista goals correnti |

## 2. Metodi interni

| Metodo | Descrizione | Problemi |
|--------|-------------|----------|
| `_init_neural_dir()` | Crea `.neural/` nel progetto target | State su filesystem, no isolamento |
| `_save_state()` | Salva YAML su disco | Nessuna persistenza strutturata |
| `_save_goals()` | Salva goals YAML | Nessuna query, no concurrent access |
| `_append_log()` | Appende a dev-log.md | Solo append, nessuna struttura |
| `_update_findings()` | Sovrascrive findings.md | Perde la storia |
| `_save_cycle()` | Salva cycle-NNN.md | Nessuna query possibile |
| `_llm_query()` | Chiama `llm.stream_query()` non-streaming | OK da riusare come pattern |
| `_kb_search()` | Cerca in KB | OK da riusare come pattern |
| `_run_claude_code()` | Lancia `claude -p` come subprocess | **No sandbox**, stessi permessi del server |
| `_bootstrap()` | Spider + KB + Ideation + Goal generation | Monolitico, ~150 righe |
| `_inner_loop()` | Per un goal: LLM istruzioni + Claude Code | OK come pattern |
| `_outer_loop()` | Valuta risultato, aggiorna findings | OK come pattern |
| `_parse_goals()` | Parsa YAML dall'LLM | **Fragile**: 30-50% fallback |
| `_generate_fallback_goals()` | Goals di default | Troppo generici |
| `_get_changed_files()` | `git diff --name-only` | OK |
| `_generate_final_report()` | Report markdown | OK |

## 3. Dataclass esposte

| Dataclass | Usata da API | Da mantenere |
|-----------|-------------|--------------|
| `Goal` | Si (asdict in SSE) | No — sostituita da GoalNode nel Goal Graph |
| `CycleResult` | Si (in SSE events) | No — nuova struttura in engine |
| `EngineState` | Si (endpoint status) | No — nuovo EngineState in Qdrant |

## 4. Endpoint API correnti (da sostituire)

| Endpoint | Metodo | Azione |
|----------|--------|--------|
| `POST /api/orchestrator/engine/start` | `engine_start()` | Crea NeuralEngine, avvia `run()` via SSE |
| `POST /api/orchestrator/engine/stop` | `engine_stop()` | Chiama `request_stop()` |
| `GET /api/orchestrator/engine/status` | `engine_status()` | Ritorna state + goals |

## 5. Dipendenze

```
NeuralEngine
  ├── orchestrator.llm (LLMProvider) — per stream_query
  ├── knowledge_base (KnowledgeBase) — per search
  ├── core.spider.SpiderAnalysis — import lazy nel _bootstrap
  ├── claude CLI ("claude -p ...") — subprocess, NO sandbox
  └── pyyaml — per state persistence su disco
```

## 6. Problemi identificati (audit-v030.md)

1. **No sandbox**: Claude Code gira con stessi permessi del server — CRITICO
2. **Goal parsing fragile**: regex su YAML LLM, 30-50% fallback
3. **State su file YAML**: no query, no concurrent access, no history
4. **Monolitico**: bootstrap + inner + outer tutto in una classe
5. **No parallelizzazione**: goals eseguiti sequenzialmente, no DAG
6. **No approval gate**: l'engine parte e va fino alla fine senza fermarsi
7. **No event bus**: yield dict custom, non integrato con EventRouter

## 7. Cosa TENERE (pattern riusabili)

- **Two-loop architecture** (inner + outer) — concetto valido, da reimplementare
- **SSE event streaming** — pattern yield dict da mantenere
- **LLM query pattern** — `_llm_query()` da estrarre in utility
- **Claude Code CLI invocation** — `_run_claude_code()` da wrappare in sandbox
- **Git diff per changed files** — `_get_changed_files()` utility riusabile

## 8. Cosa RISCRIVERE nel nuovo Execution Engine

| Vecchio | Nuovo | Modulo |
|---------|-------|--------|
| `.neural/` dir con YAML | Qdrant collections (cycles, events, approvals) | `core/execution/engine.py` |
| `Goal` lineare | `GoalNode` in DAG con dipendenze | `core/execution/goal_graph.py` |
| `_run_claude_code()` senza sandbox | SandboxManager: copia progetto, branch git, env sanitize | `core/execution/sandbox_manager.py` |
| `_parse_goals()` regex YAML | Structured output JSON da LLM | `core/execution/claude_executor.py` |
| Nessun approval | Approval gate con pause/resume | `core/execution/engine.py` |
| Nessun event bus | EventRouter.emit() per ogni step | `core/execution/engine.py` |
| `orchestrator` come dependency | Solo `LLMProvider` + `KnowledgeBase` (disaccoppiato) | Tutti |

## 9. Piano nuovi moduli (Step 4.1-4.6)

```
core/execution/
├── __init__.py          — esporta SandboxManager, GoalGraph, ClaudeExecutor, ExecutionEngine
├── sandbox_manager.py   — Step 4.1: copia progetto, git branch, env sanitize, Qdrant persist
├── goal_graph.py        — Step 4.2: DAG networkx, GoalNode, dipendenze, parallel groups
├── claude_executor.py   — Step 4.3: Claude Code CLI wrapper, istruzioni, verifica
└── engine.py            — Step 4.4: inner/outer loop, bootstrap, approval gate, SSE
```

API nuove (Step 4.5) in `api/routes/orchestrator.py`:
- `POST /api/engine/start` — avvia nuovo engine
- `GET /api/engine/stream` — SSE events
- `POST /api/engine/approve/{approval_id}` — approval gate
- `GET /api/engine/status` — stato corrente
- `POST /api/engine/stop` — graceful stop

Step 4.6: `core/neural_engine.py` riceve `DeprecationWarning`, redirect a nuovo engine.

## 10. Baseline test

- **474 test passano** prima dell'inizio di Phase 4
- Nessun test esistente copre `neural_engine.py` (confermato: nessun file `test_neural_engine*`)
- I nuovi test copriranno solo i nuovi moduli in `core/execution/`
