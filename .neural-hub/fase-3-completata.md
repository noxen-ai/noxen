# Fase 3 — Research Agent: COMPLETATA

**Data**: 2026-03-30
**Versione**: v0.5.0-alpha
**Test totali**: 430 (da 260 post-Fase 2)

## Componenti Creati

### Step 3.0 — Dependencies & Settings
- `requirements.txt`: PyGithub, gql, aiohttp, gitpython, firecrawl-py, exa-py
- `config/settings.py`: github_token, exa_api_key, firecrawl_api_key, research_sandbox_dir, research_max_repo_size_mb, research_clone_timeout_s

### Step 3.1 — GitHub Client (17 test)
- `core/research/github_client.py`
  - `RepoCandidate` dataclass
  - `GitHubClient`: search_repos(), get_repo_details(), search_by_topic() (GraphQL), rank_candidates()
  - Ranking: stars(0.3) + recency(0.2) + topic_match(0.3) + desc_match(0.2)

### Step 3.2 — Repo Analyzer (41 test)
- `core/research/repo_analyzer.py`
  - `FunctionInfo`, `ClassInfo`, `ImportInfo`, `RepoAnalysis` dataclasses
  - `RepoAnalyzer`: clone_and_analyze(), regex-based AST (Python, JS/TS, Go, Java)
  - Framework detection, endpoint extraction, important files detection
  - Async git clone con timeout, automatic cleanup

### Step 3.3 — Web Researcher (28 test)
- `core/research/web_researcher.py`
  - `WebResult`, `WebResearchResult` dataclasses
  - `WebResearcher`: search() (combined), search_exa() (semantic), scrape_url() (Firecrawl)
  - Lazy client init, parallel execution, error handling

### Step 3.4 — Skill Builder (32 test)
- `core/research/skill_builder.py`
  - `SkillDefinition`, `SkillBuildResult` dataclasses
  - `SkillBuilder`: build_skills() con LLM, _build_prompt(), _parse_llm_response()
  - JSON extraction from markdown code blocks, confidence clamping, category validation

### Step 3.5 — Research Agent (29 test)
- `core/research_agent.py`
  - `ResearchRequest`, `ResearchResult` dataclasses
  - `ResearchAgent`: research() pipeline completo, quick_search(), detect_knowledge_gap()
  - Pipeline: search_github -> analyze_repos -> web_research -> build_skills -> save_to_kb
  - Event emission, graceful error handling at each step

### Step 3.6 — Spider Integration (9 test)
- `core/spider.py` modificato:
  - `SpiderAnalysis.__init__()` accetta `research_agent` opzionale
  - `_run_research_phase()`: cerca best practices per framework/linguaggi del progetto
  - Integrato in `run_analysis()` tra Discovery e Skill Matching
  - Fix: `match_skills()` reso `async` (bug pre-esistente con `await` in sync function)

### Step 3.7 — API Endpoints (14 test)
- `api/routes/research.py`:
  - `POST /api/research` — pipeline completo
  - `GET /api/research/search` — ricerca rapida GitHub
  - `POST /api/research/gap` — detect knowledge gap
  - `GET /api/research/status` — stato componenti
- `main.py` aggiornato con import + singleton + router registration

## Architettura

```
ResearchAgent (orchestrator)
├── GitHubClient (REST + GraphQL)
│   ├── search_repos()
│   ├── search_by_topic()
│   └── rank_candidates()
├── RepoAnalyzer (clone + regex AST)
│   ├── clone_and_analyze()
│   ├── Python/JS/TS/Go/Java parsers
│   └── framework + endpoint detection
├── WebResearcher (Exa + Firecrawl)
│   ├── search_exa() (semantic)
│   └── scrape_firecrawl() (content)
├── SkillBuilder (LLM-powered)
│   ├── build_skills()
│   └── _parse_llm_response()
└── KnowledgeBase (save skills)
```

## Test Breakdown

| Componente           | Test |
|---------------------|------|
| GitHub Client        |   17 |
| Repo Analyzer        |   41 |
| Web Researcher       |   28 |
| Skill Builder        |   32 |
| Research Agent       |   29 |
| Spider Integration   |    9 |
| Research API         |   14 |
| **Fase 3 Totale**   | **170** |
| **Progetto Totale**  | **430** |
