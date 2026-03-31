# Fase 7 Completata — TUI con Textual

**Data**: 2026-03-30
**Versione**: v0.7.0-alpha (post Fase 7)
**Test baseline**: 916 (post Fase 6) -> **939** (post Fase 7)

## Riepilogo Step

### Step 7.0 — Setup Textual
- Aggiunto `textual>=0.90` a requirements.txt
- Creata struttura: `tui/`, `tui/screens/`, `tui/widgets/`, `tests/tui/`
- Installato textual 8.2.1

### Step 7.1 — App principale
- File: `tui/app.py`, `tui/app.tcss`
- NeuralHubTUI con 7 tab (TabbedContent), Header, Footer
- Bindings: 1-7 per tab, r refresh, q quit
- CSS theme con colori per status e confidence

### Step 7.2 — LiveFeed Widget
- File: `tui/widgets/live_feed.py`
- Polling ogni 2s su GET /api/events/recent
- Formattazione Rich markup con colori per sorgente
- Descrizioni leggibili per ogni tipo evento

### Step 7.3 — GoalTree Widget
- File: `tui/widgets/goal_tree.py`
- Tree widget con icone status (OK, ~~, oo, XX, --)
- Colori per priorita (CRITICAL=red, HIGH=yellow, MEDIUM=cyan, LOW=dim)
- Mostra dipendenze come nodi foglia

### Step 7.4 — SkillTable Widget
- File: `tui/widgets/skill_table.py`
- DataTable con 6 colonne: Nome, Tech, Status, Confidence, Uses, Versione
- Colori confidence: green >= 0.7, yellow >= 0.4, red < 0.4
- Colori status: green=approved, yellow=draft, cyan=review, red=rejected
- Search bar integrata

### Step 7.5 — Approval Widget
- File: `tui/widgets/approval_widget.py`
- Mostra piano pending con goals, priorita, complessita
- Bottoni Approve/Reject (disabilitati se nessun piano)
- Chiama API /api/notifications/approve e /reject

### Step 7.6 — Chat Widget
- File: `tui/widgets/chat_widget.py`
- Input con Enter per inviare
- SSE streaming da POST /api/orchestrator/chat
- Rich markup per messaggi utente e risposte

### Step 7.7 — Board Panel Widget
- File: `tui/widgets/board_panel.py`
- DataTable con delibere recenti: Tipo, Status, Decisione, Quando
- Colori decisione: green=APPROVED, yellow=IMPROVE, red=REJECTED

### Step 7.8 — System Map Widget
- File: `tui/widgets/system_map.py`
- Mostra DNA progetto: servizi, linguaggi, framework, DB, skills, LLM
- Stato "No project initialized" se non init

### Step 7.9 — CLI Entry Point + Events API
- File modificato: `cli.py` (aggiunto comando `tui`)
- File: `api/routes/events.py` (GET /api/events/recent)
- File modificato: `main.py` (registrazione events route)

### Step 7.10 — Test TUI
- File: `tests/tui/test_tui.py` (17 test)
- File: `tests/tui/test_events_api.py` (6 test)
- Test con Textual headless runner (run_test)
- Verifica: startup, tab navigation, widget presence, keyboard quit

## Layout TUI (ASCII)

```
+--[ Neural Hub ]----------------------------[ 12:34:56 ]--+
|                                                           |
| [ Live | DNA | Goals | Skills | Board | Approval | Chat ] |
|                                                           |
| +--- Live Feed ----------------------------------------+ |
| | 12:34:56 [research_agent ] Analyzing: fastapi/fastapi| |
| | 12:34:58 [skill_builder  ] Building: FastAPI DI      | |
| | 12:35:02 [board_reviewer ] Review: FastAPI (APPROVED) | |
| | 12:35:10 [execution_eng. ] Goal 1/5: Add validation  | |
| | 12:35:15 [usage_tracker  ] Skill used: redis (ok)    | |
| |                                                       | |
| +-------------------------------------------------------+ |
|                                                           |
+---[ 1 Live  2 DNA  3 Goals  4 Skills  r Refresh  q Quit]+
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| 1 | Live Feed tab |
| 2 | System DNA tab |
| 3 | Goals tab |
| 4 | Skills tab |
| 5 | Board tab |
| 6 | Approval tab |
| 7 | Chat tab |
| r | Refresh all widgets |
| q | Quit TUI |
| Enter | Send chat message (in Chat tab) |
| a | Approve plan (in Approval tab) |

## File creati/modificati

### Nuovi file
- `tui/__init__.py`
- `tui/app.py` — NeuralHubTUI main app
- `tui/app.tcss` — Textual CSS theme
- `tui/screens/__init__.py`
- `tui/screens/dashboard.py`
- `tui/screens/approval.py`
- `tui/screens/chat.py`
- `tui/widgets/__init__.py`
- `tui/widgets/live_feed.py` — LiveFeedWidget
- `tui/widgets/goal_tree.py` — GoalTreeWidget
- `tui/widgets/skill_table.py` — SkillTableWidget
- `tui/widgets/system_map.py` — SystemMapWidget
- `tui/widgets/board_panel.py` — BoardPanelWidget
- `tui/widgets/approval_widget.py` — ApprovalWidget
- `tui/widgets/chat_widget.py` — ChatWidget
- `api/routes/events.py` — Events API
- `tests/tui/__init__.py`
- `tests/tui/test_tui.py` — 17 test
- `tests/tui/test_events_api.py` — 6 test

### File modificati
- `requirements.txt` — aggiunto textual>=0.90
- `cli.py` — aggiunto comando `tui`
- `main.py` — registrazione events route

## Avvio

```bash
# Server
python main.py

# TUI (altro terminale)
python cli.py tui
# oppure con URL custom:
python cli.py tui --url http://localhost:8400
```

## Test Count Progression
- Baseline (Fase 6): 916
- TUI tests: 917 + 17 = 933
- Events API tests: 933 + 6 = 939
- **Totale nuovi test: 23**

## Note per Fase 8 (Multitenant Layer)

- SkillRepository gia supporta tenant_id (global + per-tenant)
- ContextGatherer passa tenant_id attraverso le query
- Events API non ha ancora filtro per tenant
- TUI non ha ancora selezione tenant (da aggiungere)
- API skills_v2 accetta tenant_id come query param
- Da implementare: auth middleware, tenant isolation, tenant admin
