# Neural Hub v0.2.0 → v0.3.0 — Audit Completo

> Data: 2026-03-29
> Scopo: Mappare il codice esistente, classificare ogni componente, definire il piano di migrazione incrementale verso l'architettura v0.3.0.

---

## 1. MAPPA DEL CODICE ESISTENTE

### 1.1 Core Engine

| File | LOC | Descrizione | Qualita' | Dipendenze critiche |
|------|-----|-------------|----------|---------------------|
| `core/orchestrator.py` | ~503 | Cervello del sistema. Coordina AutoDiscovery, DB, Ingestor, LLM, KB. Context gathering, skill routing, query streaming/board. | **Buona** — struttura pulita, dataclass, metodi ben separati. Skill routing naif (keyword match). | LLMProvider, AutoDiscovery, DBConnector, KnowledgeBase, PluginComposer |
| `core/llm_provider.py` | ~612 | Multi-LLM unificato. 7 provider (Ollama, Gemini, Claude, OpenAI, Grok, Mercury, Qwen). Board CDA con sintesi. Streaming SSE per tutti. | **Buona** — pattern openai_compat estensibile, consenso euristico rudimentale. Ogni chiamata crea nuovo `httpx.AsyncClient` (inefficiente). | httpx, config.settings |
| `core/neural_engine.py` | ~808 | Loop autonomo Two-Loop Architecture. Bootstrap (Spider+KB+Ideation+Goals), Inner Loop (LLM→Claude CLI), Outer Loop (eval→update). | **Media** — funziona ma e' monolitico. Goals parsing fragile (regex su YAML LLM). State via file YAML. Nessuna sandbox isolation. | Spider, LLM, KB, Claude Code CLI, pyyaml |
| `core/spider.py` | ~950+ | Analisi progetto in 4 fasi: Discovery (fs puro), DNA Profile, Skill Match (RAG), Agent Execution (3 modi). Semaphore concurrency. | **Buona** — Discovery e' solida, zero LLM. Agent system flessibile. Deep mode con Semaphore ben gestito. Issue count via string match. | LLMProvider, KnowledgeBase |
| `core/knowledge_base.py` | ~651 | Indicizzazione semantica skill/agents/docs in ChromaDB. Batch embedding via Ollama /api/embed. Hash-based incrementale. | **Media** — dipendenza hard su Ollama per embedding (sincrono!). Frontmatter parser custom rudimentale. 1 embedding per file, non per chunk. | ChromaDB, Ollama (obbligatorio per embed), httpx |
| `core/ingestor.py` | ~384 | Indicizzazione codebase utente in ChromaDB. Chunking per righe con overlap. Rispetta .gitignore. RAM-safe streaming. | **Buona** — pipeline asincrona pulita, batch insert. Usa ChromaDB default embedding (all-MiniLM-L6-v2) per i progetti, Ollama per KB — inconsistenza. | ChromaDB, chardet, gitignore_parser, ProjectManager |
| `core/project_manager.py` | ~228 | Registry progetti + collection ChromaDB per progetto. CRUD, search, persistenza JSON. | **Buona** — semplice e funzionale. | ChromaDB (PersistentClient), Ollama (OllamaEmbeddingFunction) |
| `core/auto_discovery.py` | ~281 | Scan ecosistema multi-microservizio. Detecta linguaggio, framework, DB config da .env, entry points. | **Buona** — puro Python, nessuna dipendenza LLM. Pattern matching solido. Solo 1 livello di profondita' per monorepo. | Nessuna dipendenza esterna |
| `core/plugin_composer.py` | ~262 | Compone nuovi plugin Claude Code da skill installate. Scan, copy, genera plugin.json e marketplace.json. | **Buona** — logica chiara. | ClaudeSkillParser |
| `core/claude_skill_parser.py` | ~400+ | Parser per plugin Claude Code. Legge plugin.json, SKILL.md/CLAUDE.md frontmatter. | **Buona** — parser YAML custom (senza pyyaml) funzionale. | Nessuna dipendenza esterna |
| `core/skill_manager.py` | ~254 | Dynamic import di skill Python via importlib. Registry thread-safe, pipeline prioritizzata, hot-reload. | **Buona** — design pulito, lifecycle completo (setup/teardown). | skill_base.Skill |
| `core/skill_base.py` | ~118 | ABC per le skill. SkillMetadata, SkillResult, SkillCategory, to_tool_schema(). | **Buona** — interfaccia minimale ed estensibile. | Nessuna |
| `core/skill_installer.py` | ~900+ | Installazione skill da GitHub. Analisi pre-installazione, clone, registry JSON. | **Media** — file grande, molta logica git manuale. | asyncio subprocess (git), settings |
| `core/db_connector.py` | ~250 | Connettore MySQL read-only. Schema dump, query SELECT, read-only enforcement. | **Buona** — sicurezza read-only ben implementata (SET SESSION TRANSACTION). | aiomysql |

### 1.2 API Layer

| File | LOC | Descrizione |
|------|-----|-------------|
| `api/routes/orchestrator.py` | 379 | Endpoint principali: chat SSE, query, init, spider, neural engine, settings. Entry point unificato. |
| `api/routes/bridge.py` | 252 | Bridge skill-LLM per esecuzione interattiva. |
| `api/routes/skills.py` | 236 | CRUD skill + execution endpoint. |
| `api/routes/terminal.py` | 211 | Terminal web con PTY via WebSocket. |
| `api/routes/plugins.py` | 203 | Plugin composer API. |
| `api/routes/projects.py` | 181 | Gestione progetti (register, search, reindex). |
| `api/routes/knowledge.py` | 118 | KB ingest, search, status. |
| `api/routes/chat.py` | 65 | Chat di base (pre-orchestrator). |
| `api/routes/health.py` | 10 | Health check. |

### 1.3 Config, UI, CLI

| File | LOC | Descrizione |
|------|-----|-------------|
| `config/settings.py` | 72 | Pydantic BaseSettings con tutti i parametri. Env prefix `NEURAL_HUB_`. |
| `main.py` | 138 | Entry point FastAPI. Singletons, lifespan, route registration. |
| `cli.py` | ~200 | CLI argparse + httpx per interazione col server. |
| `ui/templates/dashboard.html` | 2503 | Dashboard SPA monolitica (HTML+JS+CSS inline). Tab: Chat, Spider, Projects, Skills, Terminal, Settings. |

### 1.4 Dati e Test

| Path | Descrizione |
|------|-------------|
| `data/chroma/` | ChromaDB persistente |
| `data/projects.json` | Registry progetti |
| `data/installed_skills.json` | Registry skill installate |
| `data/knowledge_status.json` | Stato KB (~2MB con hash cache) |
| `skills/` | ~67 directory di skill repositories (clonati da GitHub) |
| `tests/` | **VUOTA** — zero test |

### 1.5 Conteggio Totale

| Metrica | Valore |
|---------|--------|
| File Python core | 16 |
| LOC Python core (excl. skills/) | ~5,800 |
| File HTML | 1 (dashboard monolitica) |
| LOC HTML/JS/CSS | 2,503 |
| API Endpoints | ~25 |
| Test | 0 |

---

## 2. CLASSIFICAZIONE PER COMPONENTE

### KEEP AS-IS — Riutilizzabile senza modifiche

| Componente | Motivazione |
|------------|-------------|
| `core/skill_base.py` | Interfaccia ABC minimale, gia' estensibile. Va bene per v0.3.0. |
| `core/auto_discovery.py` | Puro Python, zero LLM, fa il suo lavoro. Estensibile senza modifiche. |
| `core/claude_skill_parser.py` | Parser stabile, logica self-contained. |
| `core/db_connector.py` | Read-only MySQL ben implementato. Opzionale ma pulito. |
| `api/routes/health.py` | 10 righe, funziona. |
| `config/settings.py` | Pydantic-settings, va solo estesa (non modificata). |

### EVOLVE — Base solida, da estendere

| Componente | Cosa estendere | Per supportare |
|------------|---------------|----------------|
| `core/llm_provider.py` | Aggiungere: pool httpx persistente, retry con backoff, streaming structured output, modalita' ASYNC/SYNC distinte, model routing per task type | Board LLM v0.3.0 (ASYNC/SYNC), concorrenza provider-aware |
| `core/spider.py` (Discovery+DNA) | La parte Discovery e' perfetta. Match Skills e Agent Execution vanno estratti come moduli separati. Aggiungere tree-sitter per analisi AST. | Research Agent v0.3.0 |
| `core/plugin_composer.py` | Aggiungere: skill confidence scoring, board review gate, skill versioning | Skill System v0.3.0 |
| `core/skill_manager.py` | Aggiungere: confidence score, pool globale condiviso, review pipeline | Skill System autoincrementale v0.3.0 |
| `core/project_manager.py` | Sostituire ChromaDB con Qdrant client. Mantenere interfaccia CRUD. | Qdrant migration |
| `api/routes/orchestrator.py` | Aggiungere: endpoint notification, approval gate, board management | Orchestrator v0.3.0 |
| `main.py` | Aggiungere: startup Qdrant, TUI bootstrap, notification engine init | Distribuzione v0.3.0 |
| `cli.py` | Aggiungere: comandi TUI Textual, zero-config bootstrap | CLI v0.3.0 |

### REFACTOR — Logica buona, struttura da rivedere

| Componente | Problema | Azione |
|------------|----------|--------|
| `core/orchestrator.py` | Troppo accoppiato: fa context gathering + skill routing + query + DB + loop control. Il v0.3.0 richiede un orchestratore **leggero** (solo routing). | Spaccare in: `EventRouter` (leggero, legge stato da Qdrant), `ContextGatherer`, `SkillRouter`. Togliere il ragionamento dall'orchestratore. |
| `core/knowledge_base.py` | Hard dependency su Ollama per embedding. Embedding sincrono (httpx.post). Frontmatter parser duplicato. | Estrarre embedding come interfaccia astratta (Ollama/Qdrant/OpenAI). Migrare collection da ChromaDB a Qdrant. |
| `core/ingestor.py` | Usa ChromaDB default embedding per progetti ma Ollama per KB — inconsistenza. | Unificare embedding strategy. Migrare a Qdrant. |
| `ui/templates/dashboard.html` | 2503 righe monolitiche: HTML + JS + CSS inline. Impossibile da testare, estendere, o riutilizzare. | Migrare gradualmente: estrarre JS in file separati, poi componenti. Per v0.3.0 serve comunque un frontend piu' strutturato (TUI Textual e' il target primario). |

### REPLACE — Va riscritto o sostituito

| Componente | Problema | Sostituzione |
|------------|----------|-------------|
| `core/neural_engine.py` | Loop monolitico. Goals parsing fragile. State via YAML file. Nessuna sandbox. Nessuna sicurezza nell'esecuzione Claude Code. Nessuna parallelizzazione goals. | **Nuovo Execution Engine**: sandbox isolata (Docker/firejail), state in Qdrant, goals strutturati con graph dependencies, parallel execution dove possibile. |
| Persistenza YAML (`.neural/`) | File YAML sparsi nel progetto target, nessuna query, nessun concurrent access. | **Qdrant** come memoria unica: 6 collections (projects, skills, findings, cycles, events, approvals). |
| ChromaDB (tutto) | Lento su M1 con dataset grandi, no multitenant, embedding limitato, no event bus. | **Qdrant** (lightweight, performante, supporta payload filtering, multitenant via namespace). |
| Ollama obbligatorio per embedding | `KnowledgeBase._embed_batch()` chiama Ollama direttamente. Fallisce se Ollama non gira. | Embedding provider astratto: Ollama locale, OpenAI ada-002, Qdrant built-in, Sentence Transformers locale. |

### REMOVE — Non serve piu' nell'architettura target

| Componente | Motivazione |
|------------|-------------|
| `core/skill_installer.py` (parziale) | La logica di clone GitHub e' utile, ma il sistema di analisi pre-installazione e la registry JSON vanno spostati nel Skill System v0.3.0 con Qdrant. La parte git clone pura puo' restare come utility. |
| `api/routes/bridge.py` | Bridge skill-LLM interattivo legacy. Il nuovo Execution Engine gestisce tutto. Va deprecato gradualmente. |
| `api/routes/chat.py` | 65 righe, duplica funzionalita' di orchestrator/chat. Ridondante. |
| `data/knowledge_status.json` (2MB) | Hash cache salvata in JSON file — inefficiente. Va in Qdrant metadata. |

---

## 3. DIPENDENZE DA RIMUOVERE

| Dipendenza | Motivo rimozione | Sostituzione |
|------------|------------------|-------------|
| `chromadb==0.6.3` | Sostituito da Qdrant. Pesante (~200MB), lento su M1 per dataset grandi. | `qdrant-client` |
| `langchain==0.3.18` | Non usato direttamente nel codice (solo importato transitivamente da langchain-chroma). Overhead inutile. | Niente — chiamate dirette. |
| `langchain-community==0.3.17` | Dipendenza transitiva di langchain-chroma. | Niente |
| `langchain-chroma==0.2.2` | Wrapper langchain per ChromaDB. Non usato (il codice usa ChromaDB direttamente). | Niente |
| `ollama==0.4.7` | Pacchetto Python Ollama — non usato nel codice (si usa httpx direttamente). | Niente — mantieni httpx |
| `watchfiles==1.0.4` | Usato per hot-reload uvicorn, disabilitato (`reload=False`). Non necessario in produzione. | Opzionale per dev mode |

**Peso stimato rimosso**: ~300MB (chromadb + langchain + dipendenze transitive)

---

## 4. DIPENDENZE DA AGGIUNGERE

### Obbligatorie per v0.3.0

| Dipendenza | Versione | Scopo | Priorita' |
|------------|----------|-------|-----------|
| `qdrant-client` | >=1.12 | Memoria vettoriale unica, bus eventi, 6 collections. Sostituisce ChromaDB. | P1 — fondamentale |
| `fastembed` | >=0.4 | Embedding locale veloce (no Ollama dependency). Qdrant-native. | P1 — sblocca rimozione Ollama obbligatorio |
| `gitpython` | >=3.1 | Gestione git strutturata per Research Agent (clone, diff, blame). | P2 |
| `tree-sitter` | >=0.24 (gia' in requirements) | Analisi AST per Research Agent. **Gia' presente** ma non usata. | P2 |
| `tree-sitter-languages` | >=1.10 | Grammar pack per tree-sitter (Python, JS, TS, Go, etc.). | P2 |
| `textual` | >=0.90 | TUI frontend con Textual. | P2 |
| `exa-py` | >=1.0 | Exa search API per Research Agent (ricerca semantica web). | P2 |

### Per Notification Engine

| Dipendenza | Versione | Scopo |
|------------|----------|-------|
| `python-telegram-bot` | >=21 | Notifiche Telegram |
| `slack-sdk` | >=3.30 | Notifiche Slack |
| `google-auth` + `google-api-python-client` | latest | Google Chat webhook |
| `aiosmtplib` | >=3.0 | Email notifiche (SMTP async) |

### Per Research Agent

| Dipendenza | Versione | Scopo |
|------------|----------|-------|
| `PyGithub` | >=2.0 | GitHub REST API |
| `gql` + `aiohttp` | latest | GitHub GraphQL API |
| `firecrawl-py` | >=1.0 | Web scraping strutturato |

### Per Sandbox Execution

| Dipendenza | Versione | Scopo |
|------------|----------|-------|
| `docker` | >=7.0 | Docker SDK Python per sandbox isolata |

### Opzionali / Fase successiva

| Dipendenza | Scopo |
|------------|-------|
| `tenacity` | Retry decorator (sostituzione retry manuali in llm_provider) |
| `structlog` | Logging strutturato (JSON) per observability |
| `prometheus-client` | Metriche per monitoring |

---

## 5. PIANO DI MIGRAZIONE ORDINATO

### Fase 0: Preparazione (senza breaking changes)

| Step | Azione | Dipendenze | Rischio | Complessita' |
|------|--------|------------|---------|---------------|
| 0.1 | **Aggiungere test base** per i componenti KEEP (auto_discovery, skill_base, db_connector, settings). Pytest + fixture. | Nessuna | Nessuno | S |
| 0.2 | **Estrarre JS dalla dashboard** in file separati (`ui/static/js/`). Zero funzionalita' nuove. | Nessuna | Basso | S |
| 0.3 | **Creare interfaccia astratta per embedding**: `EmbeddingProvider` con implementazione Ollama e fallback locale (fastembed). | fastembed | Nessuno — aggiuntivo | M |
| 0.4 | **Pool httpx persistente** in LLMProvider (1 client per provider, non 1 per chiamata). Aggiungere retry con backoff. | Opzionale: tenacity | Basso | S |

### Fase 1: Qdrant Migration (il cuore del cambiamento)

| Step | Azione | Dipendenze | Rischio | Complessita' |
|------|--------|------------|---------|---------------|
| 1.1 | **Installare Qdrant** (Docker o binary). Creare le 6 collections: `projects`, `skills`, `findings`, `cycles`, `events`, `approvals`. | qdrant-client, Docker | Basso | M |
| 1.2 | **Migrare ProjectManager** da ChromaDB a Qdrant. Mantenere interfaccia identica (register, search, get_collection). Test di non-regressione. | Step 0.1, 1.1 | Medio — cambio storage | M |
| 1.3 | **Migrare KnowledgeBase** a Qdrant. Usare `fastembed` per embedding (via Qdrant built-in o standalone). Eliminare dipendenza Ollama per embed. | Step 0.3, 1.1 | Medio | L |
| 1.4 | **Migrare Ingestor** a Qdrant (stesso pattern di KB). | Step 1.2 | Basso | M |
| 1.5 | **Rimuovere ChromaDB + LangChain** da requirements.txt. Testare che tutto funziona solo con Qdrant. | Step 1.2-1.4 | Alto — punto di non ritorno | S |

### Fase 2: Orchestrator Refactor

| Step | Azione | Dipendenze | Rischio | Complessita' |
|------|--------|------------|---------|---------------|
| 2.1 | **Spaccare Orchestrator** in 3 moduli: `EventRouter` (leggero, solo routing), `ContextGatherer`, `SkillRouter`. L'EventRouter legge stato da Qdrant. | Step 1.1 | Medio — refactor strutturale | L |
| 2.2 | **Board LLM ASYNC/SYNC**: evolvi `board_query()` in due modalita'. ASYNC per skill/findings (fire-and-forget), SYNC per piani/architettura (blocking con approval gate). | Step 2.1 | Basso | M |
| 2.3 | **LLM Provider evoluzione**: aggiungere model routing per task type (es. Haiku per routing, Opus per architettura, Flash per batch). | Nessuna | Basso | M |

### Fase 3: Research Agent (nuovo)

| Step | Azione | Dipendenze | Rischio | Complessita' |
|------|--------|------------|---------|---------------|
| 3.1 | **Research Agent base**: Exa search + GitHub API + clone repo + tree-sitter AST analysis. Prende `ProjectDNA` come input, produce `ResearchFindings` in Qdrant. | exa-py, PyGithub, gitpython, tree-sitter | Basso — modulo nuovo | XL |
| 3.2 | **Firecrawl integration**: web scraping strutturato per documentazione esterna. | firecrawl-py | Basso | M |
| 3.3 | **Integrare Research Agent in Spider Analysis**: replace della fase "KB Research" con Research Agent reale. | Step 3.1 | Medio | M |

### Fase 4: Execution Engine (sostituzione Neural Engine)

| Step | Azione | Dipendenze | Rischio | Complessita' |
|------|--------|------------|---------|---------------|
| 4.1 | **Sandbox Manager**: esecuzione Claude Code CLI in Docker container isolato. Filesystem mount read-only + work dir scrivibile. | docker SDK | Medio | L |
| 4.2 | **Goal Graph**: sostituire lista lineare di goals con DAG (directed acyclic graph) per dipendenze tra goals e parallelizzazione. State in Qdrant. | Step 1.1 | Basso | L |
| 4.3 | **Nuovo Execution Engine**: riscrivere il loop usando EventRouter + Board LLM + Sandbox + Goal Graph. Due loop: Inner (execute) e Outer (reflect). | Step 2.1, 4.1, 4.2 | Alto — componente critico | XL |
| 4.4 | **Deprecare neural_engine.py** — redirect endpoint al nuovo engine. | Step 4.3 | Basso | S |

### Fase 5: Notification Engine + Approval Gate

| Step | Azione | Dipendenze | Rischio | Complessita' |
|------|--------|------------|---------|---------------|
| 5.1 | **Notification Engine base**: interfaccia astratta + implementazione Telegram. | python-telegram-bot | Basso | M |
| 5.2 | **Aggiungere Slack, Google Chat, Email**. | slack-sdk, google-api, aiosmtplib | Basso | M |
| 5.3 | **Approval Gate omnicanale**: l'engine si ferma, notifica, attende approvazione da qualsiasi canale. State in Qdrant collection `approvals`. | Step 5.1, 1.1 | Medio | L |

### Fase 6: Skill System v0.3.0

| Step | Azione | Dipendenze | Rischio | Complessita' |
|------|--------|------------|---------|---------------|
| 6.1 | **Confidence scoring**: ogni skill ha un confidence score che evolve con l'uso. Persistito in Qdrant. | Step 1.1 | Basso | M |
| 6.2 | **Pool globale condiviso**: skill condivise tra tenant (multitenant-ready). | Step 1.1 | Medio | L |
| 6.3 | **Board review per nuove skill**: ogni skill creata automaticamente passa review dal Board LLM prima di essere persistita. | Step 2.2, 6.1 | Basso | M |
| 6.4 | **Loop interno skill**: esplorazione → approfondimento → bozza → board → persist. | Step 6.1-6.3 | Medio | L |

### Fase 7: TUI + Distribuzione

| Step | Azione | Dipendenze | Rischio | Complessita' |
|------|--------|------------|---------|---------------|
| 7.1 | **TUI Textual**: interfaccia terminale completa con dashboard real-time, log streaming, goal progress. | textual | Basso | XL |
| 7.2 | **CLI bootstrap zero-config**: `neural-hub init` che configura Qdrant, embedding, provider automaticamente. | Step 1.1, 0.3 | Basso | M |
| 7.3 | **Multitenant layer**: namespace Qdrant per tenant, autenticazione base. | Step 1.1 | Medio | L |

---

## 6. RISCHI E PROBLEMI RILEVATI

### Debito tecnico critico

| # | Problema | Impatto | File coinvolti |
|---|----------|---------|----------------|
| 1 | **Zero test** — directory `tests/` vuota. Qualsiasi refactor e' un salto nel buio. | CRITICO — impossibile garantire non-regressione durante la migrazione. | Tutto il progetto |
| 2 | **Dashboard monolitica** — 2503 righe HTML+JS+CSS inline. Non testabile, non riutilizzabile. | ALTO — ogni modifica al frontend rischia regressioni visive. | `ui/templates/dashboard.html` |
| 3 | **Singletons in main.py** — tutti i componenti istanziati come variabili globali di modulo. No dependency injection, no test isolation. | ALTO — rende impossibile il testing unitario e il multitenant. | `main.py` |
| 4 | **Ollama obbligatorio** — `KnowledgeBase._embed_batch()` e `ProjectManager._get_embedding_fn()` hardcoded su Ollama. Se Ollama non gira, KB e search non funzionano. | ALTO — impedisce deploy cloud-only. | `core/knowledge_base.py`, `core/project_manager.py` |
| 5 | **httpx client non riutilizzato** — ogni chiamata LLM crea un nuovo `httpx.AsyncClient`. Su board mode (7 provider paralleli) crea 7 client simultanei. | MEDIO — overhead connessione, possibili socket leak. | `core/llm_provider.py` |

### Pattern problematici

| # | Pattern | Dove | Impatto |
|---|---------|------|---------|
| 6 | **God Object** — `Orchestrator` fa context gathering, skill routing, query execution, DB access, loop control. | `core/orchestrator.py` | Rende difficile il refactor in EventRouter leggero. |
| 7 | **State mutabile su settings** — `settings.active_provider = x` modifica lo stato globale a runtime. Nessuna persistenza, perso al restart. | `core/llm_provider.py`, `api/routes/orchestrator.py` | Configurazione volatile, nessuna history. |
| 8 | **Goal parsing fragile** — il Neural Engine chiede all'LLM di generare YAML e poi lo parsa. Se l'LLM non rispetta il formato, fallback generico. | `core/neural_engine.py:_parse_goals()` | 30-50% probabilita' di fallback goals invece di goals specifici. |
| 9 | **Nessuna sandbox** — Claude Code CLI gira con gli stessi permessi del server Neural Hub. Un goal malevolo potrebbe cancellare file o eseguire comandi arbitrari. | `core/neural_engine.py:_run_claude_code()` | CRITICO per sicurezza in produzione. |
| 10 | **Consenso euristico naif** — `_assess_consensus()` usa varianza lunghezza risposte come proxy per consenso. Non ha alcun valore semantico. | `core/llm_provider.py` | Consensus level inaffidabile. |
| 11 | **Embedding inconsistente** — KB usa Ollama, Ingestor usa ChromaDB default (all-MiniLM-L6-v2), ProjectManager usa Ollama. | Multiple | Risultati di ricerca incoerenti tra contesti diversi. |
| 12 | **Nessun rate limiting** sugli endpoint API. | `api/routes/*` | Vulnerabile a abuse in deploy pubblico. |
| 13 | **Route init_router pattern** — dependency injection via funzione globale. Fragile, non tipizzato, non testabile. | Tutti i file `api/routes/*.py` | Accoppiamento nascosto. |

### Accoppiamenti forti

```
main.py (singletons)
  └─> Orchestrator
        ├─> LLMProvider (diretto)
        ├─> AutoDiscovery (diretto)
        ├─> DBConnector (diretto)
        ├─> KnowledgeBase
        │     └─> ProjectManager (per ChromaDB)
        │           └─> ChromaDB + Ollama Embedding
        ├─> Ingestor
        │     └─> ProjectManager
        └─> PluginComposer
              └─> ClaudeSkillParser

NeuralEngine
  ├─> Orchestrator (intero oggetto)
  ├─> KnowledgeBase (intero oggetto)
  ├─> SpiderAnalysis (import diretto)
  └─> Claude Code CLI (subprocess)
```

L'accoppiamento Orchestrator ↔ NeuralEngine ↔ Spider e' il piu' critico da rompere.

---

## 7. QUICK WINS

Cose da fare **subito**, senza rischio di regressione, che preparano il terreno:

### 7.1 Aggiungere pytest + primi test (Complessita': S)
```bash
pip install pytest pytest-asyncio
```
Test per: `auto_discovery.scan()`, `spider.discover()`, `skill_base.Skill`, `settings`, `db_connector.schema_to_text()`. Copertura minima delle parti che non cambieranno.

### 7.2 Pool httpx in LLMProvider (Complessita': S)
Sostituire `async with httpx.AsyncClient()` in ogni metodo con un singolo `self._client` creato nel `__init__`. Riduce overhead, previene socket leak.

```python
class LLMProvider:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=API_TIMEOUT)
        # ...
    async def close(self):
        await self._client.aclose()
```

### 7.3 Estrarre JS dalla dashboard (Complessita': S)
Spostare i ~800 righe di JavaScript inline in `ui/static/js/dashboard.js`. Zero cambio funzionale.

### 7.4 Aggiungere `.neural-hub/` al .gitignore (Complessita': triviale)
La directory di audit e planning non deve entrare nel repo.

### 7.5 Fix version in main.py (Complessita': triviale)
`version="0.1.0"` → `version="0.2.0"` (riflette lo stato attuale).

### 7.6 Creare `EmbeddingProvider` interfaccia (Complessita': M)
```python
class EmbeddingProvider(abc.ABC):
    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class OllamaEmbedding(EmbeddingProvider): ...
class FastEmbedProvider(EmbeddingProvider): ...
```
Iniettare in KnowledgeBase e ProjectManager. Non cambia nulla funzionalmente ma sblocca la rimozione di Ollama obbligatorio.

### 7.7 Rimuovere dipendenze inutilizzate (Complessita': S)
Rimuovere da requirements.txt: `ollama`, `langchain`, `langchain-community`, `langchain-chroma`. Nessuno di questi package e' importato direttamente nel codice. Test: `python -c "from main import app"` deve funzionare.

### 7.8 Aggiungere logging strutturato per audit trail (Complessita': S)
Ogni azione del Neural Engine dovrebbe loggare un evento JSON con timestamp, fase, goal, risultato. Prepara il terreno per il bus eventi Qdrant.

---

## RIEPILOGO VISIVO

```
KEEP AS-IS          EVOLVE              REFACTOR            REPLACE
─────────────       ──────────          ────────────        ─────────────
skill_base.py       llm_provider.py     orchestrator.py     neural_engine.py
auto_discovery.py   spider.py (disc.)   knowledge_base.py   ChromaDB → Qdrant
claude_parser.py    plugin_composer.py  ingestor.py         YAML state → Qdrant
db_connector.py     skill_manager.py    dashboard.html      Ollama-only embed
health.py           project_manager.py
settings.py         orchestrator.py(rt)                     REMOVE
                    main.py                                 ─────────────
                    cli.py                                  langchain*
                                                            ollama (pkg)
                                                            bridge.py
                                                            chat.py (legacy)
```

---

*Documento generato per guidare l'evoluzione Neural Hub v0.2.0 → v0.3.0*
*Non e' una riscrittura. E' evoluzione incrementale.*
