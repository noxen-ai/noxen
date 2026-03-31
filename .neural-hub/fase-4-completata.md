# Phase 4 — Execution Engine: COMPLETATA

**Data**: 2026-03-30
**Test**: 628 (474 pre-esistenti + 154 nuovi)

## Moduli creati

| File | LOC | Test | Descrizione |
|------|-----|------|-------------|
| `core/execution/__init__.py` | 15 | — | Package exports |
| `core/execution/sandbox_manager.py` | 230 | 30 | Copia progetto, git branch, env sanitize, Qdrant persist |
| `core/execution/goal_graph.py` | 280 | 54 | DAG networkx, GoalNode, dipendenze, parallel groups, serialization |
| `core/execution/claude_executor.py` | 260 | 26 | Claude Code CLI wrapper, istruzioni LLM/template, verifica |
| `core/execution/engine.py` | 380 | 31 | Inner/outer loop, bootstrap, approval gate, SSE events |
| API endpoints (in orchestrator.py) | ~90 | 13 | 5 nuovi endpoint /api/engine/* |

## Step completati

| Step | Descrizione | Output |
|------|-------------|--------|
| 4.0 | Analisi pre-sviluppo | `.neural-hub/engine-analysis.md` |
| 4.1 | Sandbox Manager | `core/execution/sandbox_manager.py` + 30 test |
| 4.2 | Goal Graph | `core/execution/goal_graph.py` + 54 test, `networkx` aggiunto |
| 4.3 | Claude Code Executor | `core/execution/claude_executor.py` + 26 test |
| 4.4 | Execution Engine | `core/execution/engine.py` + 31 test |
| 4.5 | API Routes | 5 endpoint in orchestrator.py + 13 test |
| 4.6 | Deprecate neural_engine.py | DeprecationWarning aggiunto |

## Nuovi endpoint API

| Endpoint | Metodo | Descrizione |
|----------|--------|-------------|
| `/api/engine/start` | POST | Avvia Execution Engine (SSE stream) |
| `/api/engine/approve` | POST | Approva piano (sblocca approval gate) |
| `/api/engine/reject` | POST | Rifiuta piano (ferma esecuzione) |
| `/api/engine/stop` | POST | Stop graceful del loop |
| `/api/engine/status` | GET | Stato corrente + goal graph |

## Architettura

```
ExecutionEngine
├── SandboxManager
│   ├── _copy_project() — shutil.copytree con EXCLUDE_PATTERNS
│   ├── _setup_git() — git init + branch neural-hub/run-*
│   ├── _sanitize_env_files() — redact chiavi sensibili
│   └── _persist_sandbox_info() — Qdrant collection "cycles"
├── GoalGraph (networkx DAG)
│   ├── GoalNode — id, title, description, priority, category, depends_on
│   ├── add_goal() — con cycle detection
│   ├── get_ready_goals() — dipendenze soddisfatte, ordinati per priorita'
│   ├── get_parallel_groups() — topological generations
│   └── to_dict() / from_dict() — serializzazione JSON
├── ClaudeExecutor
│   ├── generate_instructions() — LLM o template-based
│   ├── execute() — `claude -p` subprocess con timeout
│   ├── verify() — valutazione LLM del risultato
│   └── _get_changed_files() — git diff
└── Engine Loop
    ├── _bootstrap() — Spider + KB + LLM goal generation
    ├── Approval Gate — asyncio.Event, approve()/reject()
    ├── _inner_loop() — per goal: istruzioni + Claude Code
    ├── _outer_loop() — verifica + aggiorna goal status
    └── SSE events — yield dict per frontend
```

## Dipendenze aggiunte

```
networkx>=3.0    (Goal Graph DAG)
```

## Miglioramenti vs neural_engine.py

| Aspetto | Prima (neural_engine.py) | Dopo (execution/) |
|---------|-------------------------|-------------------|
| Sandbox | Nessuna — stessi permessi server | Copia isolata + branch git |
| Goals | Lista lineare YAML | DAG networkx con dipendenze |
| Goal parsing | Regex su YAML LLM (30-50% fallback) | JSON structured + fallback robusto |
| Parallelismo | Nessuno | Parallel groups via topological generations |
| Approval | Nessuno — gira fino alla fine | Gate con approve/reject |
| State | File YAML in .neural/ | In-memory + Qdrant persist opzionale |
| Event bus | yield dict custom | EventRouter.emit() integrato |
| Sicurezza | .env copiati con segreti | Sanitizzazione automatica |
| API | 3 endpoint in orchestrator | 5 endpoint dedicati + backward compat |

## Retrocompatibilita'

- I vecchi endpoint `/api/orchestrator/engine/*` funzionano ancora
- `core/neural_engine.py` ha `DeprecationWarning` ma resta importabile
- Nessun modulo esistente modificato (eccetto orchestrator.py per nuovi endpoint)

## Test count evolution

| Fase | Test |
|------|------|
| Phase 1 (Qdrant) | 130 |
| Phase 2 (Orchestrator) | 260 |
| Phase 3 (Research Agent) | 430 |
| Tree-sitter migration | 474 |
| **Phase 4 (Execution Engine)** | **628** |
