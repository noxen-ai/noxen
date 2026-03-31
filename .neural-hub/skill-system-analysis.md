# Skill System v0.3.0 — Pre-Development Analysis

**Data**: 2026-03-30
**Fase**: 6 — Skill System v0.3.0

---

## 1. COSA ESISTE GIA'

### 1.1 Skill Runtime (`core/skill_base.py` + `core/skill_manager.py`)

**skill_base.py** (118 LOC):
- `SkillCategory` enum (8 valori: code_analysis, code_generation, search, devops, data, integration, utility, custom)
- `SkillPriority` enum (1-5: orchestrator, primary, secondary, utility, background)
- `SkillMetadata` dataclass (name, description, version, author, category, tags, parameters, auto_approve, priority, depends_on)
- `SkillResult` dataclass (success, data, error, metadata)
- `Skill` ABC con: setup(), teardown(), execute(), call_skill(), to_tool_schema()

**skill_manager.py** (254 LOC):
- Dynamic import di skill Python via `importlib`
- Registry thread-safe con asyncio.Lock
- Pipeline prioritizzata (`run_pipeline()`)
- Hot-reload (`reload_skill()`)
- Recursive scan con profondita' max 3

**Nota**: Questo e' il sistema di skill **runtime** (Python classes). La Fase 6 crea un sistema di skill **knowledge** (SKILL.md con metriche, lifecycle, board review). I due sistemi coesistono.

### 1.2 Plugin Composer (`core/plugin_composer.py`)

- Scan `skills/` directory per plugin Claude Code
- Parse frontmatter di SKILL.md/CLAUDE.md via `ClaudeSkillParser`
- Compone nuovi plugin da skill selezionate
- Genera plugin.json + marketplace.json
- **Nessun concetto di lifecycle, confidence, board review**

### 1.3 Skill Builder (`core/research/skill_builder.py`)

- Genera `SkillDefinition` dai risultati della ricerca (RepoAnalysis + WebResearchResult)
- Usa LLM per generare JSON array di skill
- `SkillDefinition` dataclass: name, description, category, tags, content, source_repos, source_urls, confidence (0.0-1.0)
- **Produce skill ma NON le persiste**. Nessuna integrazione con Qdrant o lifecycle.

### 1.4 Skill Router (`core/skill_router.py`)

- Keyword matching (SKILL_ROUTING dict con 8 categorie)
- Semantic search via Qdrant collection "skills" (tentativo con fallback)
- **Cerca nella collection Qdrant "skills" ma non sa di lifecycle/confidence**

### 1.5 Context Gatherer (`core/context_gatherer.py`)

- Raccoglie contesto per il LLM: KB, RAG, DB, skill routing
- Usa `skill_router.route()` per keyword matching
- **Nessun filtro per confidence o status**

### 1.6 Qdrant Client (`core/qdrant_client.py`)

- Collection "skills" gia' definita (vector_size=384)
- Solo operazioni base: health_check, get_collection_counts
- **Nessuna API CRUD per skill** — accesso diretto via `client` property

### 1.7 Embedding Provider (`core/embedding_provider.py`)

- `FastEmbedProvider` con BAAI/bge-small-en-v1.5 (384 dim)
- Singleton pattern con `get_instance()`
- Metodo `embed(texts: list[str]) -> list[list[float]]`

---

## 2. COSA MANCA

| Componente | Descrizione | File target |
|-----------|-------------|-------------|
| **Skill Lifecycle Model** | Enum SkillStatus, SkillSource, SkillMetrics con confidence scoring, Skill dataclass completa con to/from Qdrant | `core/skills/lifecycle.py` |
| **Skill Repository** | CRUD Qdrant per skill, search semantica, filtri per status/confidence/tenant | `core/skills/repository.py` |
| **Board Reviewer** | Submit skill al Board LLM per review, aggregate votes, approve/improve/reject | `core/skills/board_reviewer.py` |
| **Skill Updater** | Ciclo di miglioramento: feedback -> ricerca -> aggiornamento -> re-review | `core/skills/updater.py` |
| **Usage Tracker** | Traccia utilizzo skill, registra outcome, aggiorna metriche | `core/skills/usage_tracker.py` |
| **ContextGatherer integration** | Usa SkillRepository.search() con filtro confidence >= 0.4 | `core/context_gatherer.py` (mod) |
| **API v2** | Endpoint REST per pool, approve, reject, improve, stats, history | `api/routes/skills_v2.py` |

---

## 3. DIPENDENZE TRA STEP

```
Step 6.1 (Lifecycle)
  └── Step 6.2 (Repository) -- usa Skill, SkillMetrics
        ├── Step 6.3 (Board Reviewer) -- usa SkillRepository
        ├── Step 6.5 (Usage Tracker) -- usa SkillRepository
        └── Step 6.6 (ContextGatherer) -- usa SkillRepository
Step 6.3 (Board Reviewer)
  └── Step 6.4 (Updater) -- usa BoardReviewer + SkillRepository
Step 6.7 (API) -- usa tutti i componenti
```

---

## 4. RELAZIONE CON COMPONENTI ESISTENTI

| Componente esistente | Interazione con Fase 6 |
|---------------------|----------------------|
| `skill_base.py` + `skill_manager.py` | **Coesistono**. Skill runtime (Python) != Skill knowledge (SKILL.md). Non modificati. |
| `plugin_composer.py` | **Non modificato**. Plugin composer gestisce plugin Claude Code, non il lifecycle. |
| `research/skill_builder.py` | **Produttore**. Il SkillBuilder produce SkillDefinition che il Repository persiste come Skill draft. |
| `skill_router.py` | **Evolve** indirettamente tramite ContextGatherer (Step 6.6). Il vecchio keyword routing resta come fallback. |
| `context_gatherer.py` | **Modificato** (Step 6.6). Usa SkillRepository per semantic search con confidence filter. |
| `qdrant_client.py` | **Usato**. Repository usa la collection "skills" gia' definita. |
| `embedding_provider.py` | **Usato**. Repository usa FastEmbedProvider per embedding skill. |
| `event_router.py` | **Usato**. Board reviewer emette eventi per skill_needs_improvement e skill_review_completed. |

---

## 5. DECISIONI ARCHITETTURALI

1. **Package `core/skills/`** (nuovo) per separare dal vecchio `core/skill_manager.py`
2. **SkillMetrics.confidence_score** calcolato con formula: success_rate * 0.6 + partial_rate * 0.2 + recency_bonus (0-0.2)
3. **Board review ASYNC** via asyncio.create_task — non blocca il Research Agent
4. **Tenant support**: skill hanno tenant_id ("global" default), ricerca cerca prima nel tenant poi global
5. **Qdrant come unico storage**: niente JSON file, niente YAML state
6. **Backward compatible**: SkillRouter.route() keyword matching resta attivo come fallback
