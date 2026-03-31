"""Noxen - Spider Analysis Engine.

Analisi autonoma di qualsiasi progetto in 4 fasi:
  1. DISCOVERY  — scan filesystem (Python puro, zero LLM)
  2. DNA PROFILE — genera profilo testuale del progetto
  3. SKILL MATCH — query RAG sulla KB per trovare skill/agenti rilevanti
  4. AGENT EXEC  — lancia LLM con contesto mirato (3 modalita')

Modalita':
  - quick: 1 singola query LLM con mega-contesto unificato
  - deep:  N query LLM parallele (1 per agente specializzato)
  - full:  N agenti paralleli + cross-reference + board synthesis
"""

from __future__ import annotations

import asyncio
from core.logger import get_logger
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

logger = get_logger("noxen.spider")

# ── Costanti Discovery ────────────────────────────────────────────────

# Directory da ignorare durante lo scan
SKIP_DIRS = {
    "node_modules", "vendor", "__pycache__", ".git", ".svn", ".hg",
    "dist", "build", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", "coverage", ".idea", ".vscode", "target", "bin", "obj",
    ".terraform", ".serverless", "bower_components", "jspm_packages",
}

# File marker → linguaggio
LANG_MARKERS = {
    "composer.json": "PHP", "artisan": "PHP",
    "package.json": "JavaScript/TypeScript", "tsconfig.json": "TypeScript",
    "requirements.txt": "Python", "pyproject.toml": "Python", "Pipfile": "Python",
    "setup.py": "Python", "setup.cfg": "Python",
    "Cargo.toml": "Rust", "go.mod": "Go", "go.sum": "Go",
    "Gemfile": "Ruby", "Rakefile": "Ruby",
    "pom.xml": "Java", "build.gradle": "Java", "build.gradle.kts": "Kotlin",
    "mix.exs": "Elixir", "rebar.config": "Erlang",
    "Package.swift": "Swift", "*.csproj": "C#", "*.fsproj": "F#",
}

# Pattern framework detection (file content)
FRAMEWORK_DETECT = {
    "Laravel": ["laravel/framework", "Illuminate\\"],
    "Symfony": ["symfony/framework-bundle"],
    "Express": ['"express"', "require('express')"],
    "NestJS": ["@nestjs/core"],
    "Next.js": ['"next"', "next/"],
    "Nuxt": ['"nuxt"', "@nuxt/"],
    "Vue": ['"vue"', "createApp("],
    "React": ['"react"', "from 'react'"],
    "Angular": ["@angular/core"],
    "Django": ["django", "DJANGO_SETTINGS_MODULE"],
    "Flask": ["from flask", '"flask"'],
    "FastAPI": ["from fastapi", '"fastapi"'],
    "Rails": ["gem 'rails'", 'gem "rails"'],
    "Spring Boot": ["spring-boot-starter"],
    "Gin": ["github.com/gin-gonic/gin"],
    "Echo": ["github.com/labstack/echo"],
    "Actix": ["actix-web"],
    "Rocket": ["rocket"],
    "Phoenix": ["phoenix"],
    "ASP.NET": ["Microsoft.AspNetCore"],
}

# Infra/tool detection
INFRA_FILES = {
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose", "docker-compose.yaml": "Docker Compose",
    "compose.yml": "Docker Compose", "compose.yaml": "Docker Compose",
    ".dockerignore": "Docker",
    "Makefile": "Make",
    "Jenkinsfile": "Jenkins",
    ".gitlab-ci.yml": "GitLab CI",
    ".github/workflows": "GitHub Actions",
    ".circleci/config.yml": "CircleCI",
    ".travis.yml": "Travis CI",
    "Procfile": "Heroku",
    "serverless.yml": "Serverless",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "helm": "Helm",
    ".env": "Environment Variables",
    ".env.example": "Environment Variables",
    "nginx.conf": "Nginx",
    "redis.conf": "Redis",
    "prisma/schema.prisma": "Prisma ORM",
    "drizzle.config.ts": "Drizzle ORM",
    "knexfile.js": "Knex.js",
    "alembic.ini": "Alembic (SQLAlchemy)",
    "ormconfig.json": "TypeORM",
    "sequelize.config.js": "Sequelize",
}

# Test framework detection
TEST_PATTERNS = {
    "tests/": "test suite",
    "test/": "test suite",
    "__tests__/": "Jest tests",
    "spec/": "RSpec/Jasmine",
    "cypress/": "Cypress E2E",
    "playwright/": "Playwright E2E",
    "pytest.ini": "pytest",
    "jest.config": "Jest",
    ".mocharc": "Mocha",
    "phpunit.xml": "PHPUnit",
    "vitest.config": "Vitest",
}

# Extension → linguaggio per conteggio LOC
EXT_LANG = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "React/TSX",
    ".jsx": "React/JSX", ".php": "PHP", ".rb": "Ruby", ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".kt": "Kotlin", ".swift": "Swift", ".cs": "C#",
    ".ex": "Elixir", ".erl": "Erlang", ".vue": "Vue SFC", ".svelte": "Svelte",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".less": "LESS",
    ".sql": "SQL", ".sh": "Shell", ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON", ".xml": "XML", ".md": "Markdown", ".toml": "TOML",
}


# ── Data Classes ──────────────────────────────────────────────────────

@dataclass
class ProjectDNA:
    """Profilo completo del progetto generato dalla discovery."""
    path: str
    name: str
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    infra: list[str] = field(default_factory=list)
    test_tools: list[str] = field(default_factory=list)
    has_docker: bool = False
    has_ci: bool = False
    has_db: bool = False
    has_tests: bool = False
    has_api: bool = False
    db_type: str = ""
    total_files: int = 0
    total_dirs: int = 0
    code_files: int = 0
    loc_by_lang: dict[str, int] = field(default_factory=dict)
    total_loc: int = 0
    services: list[dict] = field(default_factory=list)  # Microservizi trovati
    key_files: list[str] = field(default_factory=list)   # File importanti trovati
    structure_tree: str = ""                              # Top-level tree ASCII
    env_vars: list[str] = field(default_factory=list)     # .env keys (senza valori)
    api_endpoints_estimate: int = 0

    def to_profile_text(self) -> str:
        """Genera un profilo testuale leggibile del progetto."""
        lines = [
            f"PROGETTO: {self.name}",
            f"Path: {self.path}",
            f"",
            f"STACK:",
            f"  Linguaggi: {', '.join(self.languages) or 'N/A'}",
            f"  Framework: {', '.join(self.frameworks) or 'nessuno rilevato'}",
            f"  Infrastruttura: {', '.join(self.infra) or 'nessuna'}",
            f"  Testing: {', '.join(self.test_tools) or 'nessun test trovato'}",
            f"",
            f"DIMENSIONI:",
            f"  File totali: {self.total_files} ({self.code_files} codice)",
            f"  LOC totali: {self.total_loc:,}",
        ]
        if self.loc_by_lang:
            for lang, loc in sorted(self.loc_by_lang.items(), key=lambda x: -x[1])[:8]:
                lines.append(f"    {lang}: {loc:,} righe")

        lines.extend([
            f"",
            f"CARATTERISTICHE:",
            f"  Docker: {'si' if self.has_docker else 'no'}",
            f"  CI/CD: {'si' if self.has_ci else 'no'}",
            f"  Database: {self.db_type or 'non rilevato'}",
            f"  Test: {'si' if self.has_tests else 'no'}",
            f"  API: {'si (~' + str(self.api_endpoints_estimate) + ' endpoint)' if self.has_api else 'no'}",
        ])

        if self.services:
            lines.append(f"")
            lines.append(f"MICROSERVIZI ({len(self.services)}):")
            for svc in self.services[:10]:
                lines.append(f"  - {svc['name']}: {svc.get('language', '?')} / {svc.get('framework', '?')}")

        if self.env_vars:
            lines.append(f"")
            lines.append(f"VARIABILI AMBIENTE ({len(self.env_vars)}):")
            for v in self.env_vars[:20]:
                lines.append(f"  - {v}")

        if self.structure_tree:
            lines.append(f"")
            lines.append(f"STRUTTURA:")
            lines.append(self.structure_tree)

        return "\n".join(lines)


@dataclass
class AgentTask:
    """Task assegnato a un agente specializzato."""
    agent_name: str
    domain: str         # security, quality, architecture, db, testing, devops, performance, api
    prompt: str         # Prompt specifico per l'agente
    context: str        # Contesto aggiuntivo dal RAG
    priority: int = 1   # 1=critico, 5=opzionale


@dataclass
class AgentReport:
    """Report prodotto da un singolo agente."""
    agent_name: str
    domain: str
    content: str
    issues_found: int = 0
    severity_high: int = 0
    severity_medium: int = 0
    severity_low: int = 0
    latency_ms: int = 0
    error: str = ""


@dataclass
class SpiderReport:
    """Report completo dell'analisi Spider."""
    project_name: str
    mode: str           # quick, deep, full
    dna: ProjectDNA | None = None
    health_score: int = 0
    agent_reports: list[AgentReport] = field(default_factory=list)
    synthesis: str = ""
    total_issues: int = 0
    elapsed_seconds: float = 0


# ── Agent Definitions ─────────────────────────────────────────────────

SPIDER_AGENTS = {
    "security": {
        "name": "Security Auditor",
        "domain": "security",
        "priority": 1,
        "trigger_keywords": [],  # Sempre attivo
        "prompt_template": (
            "Sei un Security Auditor esperto. Analizza questo progetto e trova vulnerabilita':\n"
            "- SQL Injection, XSS, CSRF\n"
            "- Credenziali hardcoded, secrets esposti\n"
            "- Endpoint non autenticati\n"
            "- Dipendenze con CVE note\n"
            "- Configurazioni insicure (CORS, headers, TLS)\n"
            "- Permessi file/directory\n\n"
            "Per ogni issue: severita' (CRITICO/ALTO/MEDIO/BASSO), descrizione, file coinvolto, fix consigliata.\n"
            "Se non trovi problemi in un'area, dillo esplicitamente."
        ),
    },
    "quality": {
        "name": "Code Quality Reviewer",
        "domain": "quality",
        "priority": 1,
        "trigger_keywords": [],
        "prompt_template": (
            "Sei un Code Quality Expert. Analizza la qualita' del codice:\n"
            "- Code smells: funzioni >50 righe, God Objects, duplicazioni\n"
            "- Violazioni SOLID (Single Responsibility, Open/Closed, etc.)\n"
            "- Accoppiamento eccessivo tra moduli\n"
            "- Naming inconsistente\n"
            "- Error handling mancante o inadeguato\n"
            "- Pattern anti-pattern (callback hell, deeply nested conditions)\n\n"
            "Top 10 problemi con: descrizione, impatto, esempio codice fix."
        ),
    },
    "architecture": {
        "name": "Architecture Analyst",
        "domain": "architecture",
        "priority": 1,
        "trigger_keywords": [],
        "prompt_template": (
            "Sei un Software Architect senior. Analizza l'architettura:\n"
            "- Layer identification (API, business logic, data access)\n"
            "- Pattern usati (MVC, Repository, CQRS, Event-Driven, etc.)\n"
            "- Dependency graph tra moduli — ci sono dipendenze circolari?\n"
            "- Separation of concerns — e' rispettata?\n"
            "- Single points of failure\n"
            "- Scalabilita' orizzontale: il sistema lo supporta?\n\n"
            "Genera un diagramma ASCII delle relazioni principali.\n"
            "Suggerisci miglioramenti architetturali concreti."
        ),
    },
    "database": {
        "name": "Database Analyst",
        "domain": "database",
        "priority": 2,
        "trigger_keywords": ["db", "sql", "mysql", "postgres", "mongo", "database", "migration", "prisma", "orm"],
        "prompt_template": (
            "Sei un Database Expert. Analizza tutto cio' che riguarda il database:\n"
            "- Schema: normalizzazione, relazioni mancanti, indici assenti\n"
            "- Query nel codice: N+1, SELECT *, JOIN senza indice\n"
            "- Migration: sono consistenti? Ci sono rollback?\n"
            "- Connection management: pool, timeout, retry\n"
            "- Sicurezza: prepared statements, SQL injection\n\n"
            "Per ogni issue: query/codice originale, problema, versione ottimizzata."
        ),
    },
    "testing": {
        "name": "QA Engineer",
        "domain": "testing",
        "priority": 2,
        "trigger_keywords": ["test", "spec", "coverage", "jest", "pytest", "phpunit"],
        "prompt_template": (
            "Sei un QA Engineer. Analizza la copertura e qualita' dei test:\n"
            "- Coverage stimata: quali aree sono coperte e quali no?\n"
            "- Tipi di test presenti: unit, integration, e2e\n"
            "- Test quality: i test verificano davvero la logica o sono superficiali?\n"
            "- Missing test cases: quali funzioni/moduli critici non hanno test?\n"
            "- Test infrastructure: CI integration, test database, fixtures\n\n"
            "Genera una lista di test prioritari da scrivere (top 10)."
        ),
    },
    "devops": {
        "name": "DevOps Engineer",
        "domain": "devops",
        "priority": 2,
        "trigger_keywords": ["docker", "ci", "deploy", "kubernetes", "pipeline", "terraform"],
        "prompt_template": (
            "Sei un DevOps Engineer senior. Analizza infrastruttura e deploy:\n"
            "- Dockerfile: e' ottimizzato? Multi-stage? Layer caching?\n"
            "- CI/CD: pipeline completa? Lint, test, build, deploy?\n"
            "- Environment management: .env, secrets, config per ambiente\n"
            "- Monitoring: health checks, logging, alerting\n"
            "- Container orchestration: docker-compose adeguato?\n"
            "- Security: immagini base aggiornate? Non-root user?\n\n"
            "Suggerisci la pipeline CI/CD ideale per questo progetto."
        ),
    },
    "performance": {
        "name": "Performance Engineer",
        "domain": "performance",
        "priority": 3,
        "trigger_keywords": ["cache", "redis", "performance", "slow", "optimization"],
        "prompt_template": (
            "Sei un Performance Engineer. Identifica bottleneck:\n"
            "- I/O blocking: chiamate sync che bloccano, file I/O sul main thread\n"
            "- Memory leaks: risorse non rilasciate, event listener non rimossi\n"
            "- Cache mancante: query ripetute, computazioni cacheable\n"
            "- N+1 queries e accesso DB non ottimizzato\n"
            "- Bundle size (frontend): dipendenze pesanti, tree shaking\n"
            "- Connection pool: configurazione, dimensionamento\n\n"
            "Per ogni issue: impatto stimato, soluzione con codice."
        ),
    },
    "api": {
        "name": "API Reviewer",
        "domain": "api",
        "priority": 3,
        "trigger_keywords": ["api", "rest", "endpoint", "route", "controller", "graphql"],
        "prompt_template": (
            "Sei un API Design Expert. Analizza le API del progetto:\n"
            "- REST compliance: naming, HTTP methods, status codes\n"
            "- Validazione input: manca? E' consistente?\n"
            "- Autenticazione/Autorizzazione: come e' implementata?\n"
            "- Rate limiting: presente?\n"
            "- Documentazione: le API sono documentate?\n"
            "- Versioning: c'e' una strategia?\n"
            "- Error handling: formato errori consistente?\n\n"
            "Genera la docs delle API trovate in formato Markdown."
        ),
    },
}


# ── Spider Analysis Engine ────────────────────────────────────────────

class SpiderAnalysis:
    """Motore di analisi autonoma — il ragno che tesse la ragnatela."""

    def __init__(self, orchestrator: Any, knowledge_base: Any = None, research_agent: Any = None):
        self.orchestrator = orchestrator
        self.kb = knowledge_base
        self.llm = orchestrator.llm
        self.research_agent = research_agent

    # ── Phase 1: Discovery (Python puro) ──────────────────────────────

    def discover(self, project_path: str) -> ProjectDNA:
        """Scansiona il progetto e genera il DNA — zero LLM, puro Python."""
        t0 = time.time()
        root = Path(project_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Directory non trovata: {root}")

        dna = ProjectDNA(path=str(root), name=root.name)
        logger.info(f"[Spider] Discovery: {root}")

        # Scan filesystem
        all_files: list[Path] = []
        all_dirs: set[str] = set()
        lang_counter: Counter = Counter()
        loc_counter: Counter = Counter()

        for dirpath, dirnames, filenames in os.walk(root):
            # Filtra directory da ignorare
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            rel_dir = os.path.relpath(dirpath, root)
            if rel_dir != ".":
                all_dirs.add(rel_dir)

            for fname in filenames:
                fpath = Path(dirpath) / fname
                rel_path = str(fpath.relative_to(root))
                all_files.append(fpath)

                # Language detection by extension
                ext = fpath.suffix.lower()
                if ext in EXT_LANG:
                    lang = EXT_LANG[ext]
                    lang_counter[lang] += 1
                    # Conta LOC (solo file < 1MB)
                    try:
                        if fpath.stat().st_size < 1_000_000:
                            lines = fpath.read_text(errors="ignore").count("\n")
                            loc_counter[lang] += lines
                    except Exception:
                        pass

                # Language markers
                if fname in LANG_MARKERS:
                    dna.languages.append(LANG_MARKERS[fname])

                # Framework detection (solo certi file)
                if fname in ("composer.json", "package.json", "requirements.txt",
                             "pyproject.toml", "Pipfile", "Cargo.toml", "go.mod",
                             "Gemfile", "pom.xml", "build.gradle"):
                    self._detect_frameworks(fpath, dna)

                # Infra detection
                if fname in INFRA_FILES:
                    dna.infra.append(INFRA_FILES[fname])
                for pattern, infra_name in INFRA_FILES.items():
                    if "/" in pattern and rel_path.startswith(pattern):
                        dna.infra.append(infra_name)

                # Test detection
                for pattern, test_name in TEST_PATTERNS.items():
                    if pattern.endswith("/"):
                        if rel_path.startswith(pattern) or f"/{pattern}" in rel_path:
                            dna.test_tools.append(test_name)
                    elif fname.startswith(pattern.rstrip("*")):
                        dna.test_tools.append(test_name)

                # .env key extraction (senza valori)
                if fname in (".env", ".env.example", ".env.sample"):
                    self._extract_env_keys(fpath, dna)

                # API endpoint estimation
                if ext in (".py", ".php", ".js", ".ts", ".rb", ".go", ".java"):
                    try:
                        if fpath.stat().st_size < 500_000:
                            content = fpath.read_text(errors="ignore")
                            dna.api_endpoints_estimate += len(re.findall(
                                r'@(app\.|router\.|Route|Get|Post|Put|Delete|Patch|RequestMapping|route)',
                                content
                            ))
                    except Exception:
                        pass

        # Deduplica e finalizza
        dna.languages = sorted(set(dna.languages))
        dna.frameworks = sorted(set(dna.frameworks))
        dna.infra = sorted(set(dna.infra))
        dna.test_tools = sorted(set(dna.test_tools))
        dna.total_files = len(all_files)
        dna.total_dirs = len(all_dirs)
        dna.code_files = sum(lang_counter.values())
        dna.loc_by_lang = dict(loc_counter.most_common())
        dna.total_loc = sum(loc_counter.values())
        dna.has_docker = any("Docker" in i for i in dna.infra)
        dna.has_ci = any(ci in " ".join(dna.infra) for ci in
                         ["GitHub Actions", "GitLab CI", "Jenkins", "CircleCI", "Travis"])
        dna.has_tests = bool(dna.test_tools)
        dna.has_api = dna.api_endpoints_estimate > 0

        # DB detection
        dna.has_db, dna.db_type = self._detect_database(root, all_files)

        # Struttura top-level
        dna.structure_tree = self._generate_tree(root)

        # Key files
        dna.key_files = self._find_key_files(root, all_files)

        elapsed = time.time() - t0
        logger.info(
            f"[Spider] Discovery completa in {elapsed:.1f}s: "
            f"{dna.total_files} file, {dna.total_loc:,} LOC, "
            f"langs={dna.languages}, fw={dna.frameworks}"
        )

        return dna

    # ── Phase 2: Skill Matching (RAG) ─────────────────────────────────

    async def match_skills(self, dna: ProjectDNA) -> list[AgentTask]:
        """Trova skill/agenti rilevanti nella KB e genera task list."""
        profile = dna.to_profile_text()

        # Determina quali agenti attivare in base al DNA
        tasks: list[AgentTask] = []

        for agent_id, agent_def in SPIDER_AGENTS.items():
            # Agenti priority 1 sono SEMPRE attivi
            activate = agent_def["priority"] == 1

            # Agenti priority 2-3: attiva solo se il progetto ha feature rilevanti
            if not activate:
                keywords = agent_def["trigger_keywords"]
                if keywords:
                    profile_lower = profile.lower()
                    if any(kw in profile_lower for kw in keywords):
                        activate = True

                # Attivazione euristica basata sul DNA
                if agent_id == "database" and dna.has_db:
                    activate = True
                elif agent_id == "testing" and (dna.has_tests or dna.total_loc > 1000):
                    activate = True
                elif agent_id == "devops" and (dna.has_docker or dna.has_ci):
                    activate = True
                elif agent_id == "performance" and dna.total_loc > 5000:
                    activate = True
                elif agent_id == "api" and dna.has_api:
                    activate = True

            if not activate:
                continue

            # Cerca contesto specifico nella KB per questo dominio
            kb_context = ""
            if self.kb:
                try:
                    query = f"{agent_def['domain']} best practices {' '.join(dna.frameworks)} {' '.join(dna.languages)}"
                    results = await self.kb.search(query, n_results=3)
                    if results:
                        kb_context = "\n\nCONOSCENZA SPECIFICA:\n"
                        for r in results:
                            meta = r.get("metadata", {})
                            kb_context += f"\n--- {meta.get('plugin', '')}/{meta.get('file_path', '')} ---\n"
                            kb_context += r.get("document", "")[:2000] + "\n"
                except Exception as e:
                    logger.warning(f"[Spider] KB search failed for {agent_id}: {e}")

            task = AgentTask(
                agent_name=agent_def["name"],
                domain=agent_id,
                prompt=agent_def["prompt_template"],
                context=kb_context,
                priority=agent_def["priority"],
            )
            tasks.append(task)

        # Ordina per priorita'
        tasks.sort(key=lambda t: t.priority)

        logger.info(f"[Spider] Skill matching: {len(tasks)} agenti attivati su {len(SPIDER_AGENTS)} disponibili")
        for t in tasks:
            logger.info(f"  [{t.priority}] {t.agent_name} ({t.domain})")

        return tasks

    # ── Phase 2.5: Research (optional) ──────────────────────────────────

    async def _run_research_phase(self, dna: "ProjectDNA") -> dict:
        """Lancia Research Agent per colmare lacune nella KB.

        Analizza i framework/linguaggi del progetto e cerca
        best practices non ancora coperte dalle skill esistenti.

        Returns:
            dict con research_results e skills_generated count.
        """
        if not self.research_agent:
            return {"skipped": True, "reason": "no research agent"}

        from core.research_agent import ResearchRequest

        # Costruisci query dai framework e linguaggi del progetto
        topics = list(dna.frameworks) + list(dna.languages)
        if not topics:
            return {"skipped": True, "reason": "no frameworks/languages detected"}

        query = " ".join(topics[:5]) + " best practices architecture"

        try:
            request = ResearchRequest(
                query=query,
                language=dna.languages[0] if dna.languages else None,
                max_repos=3,
                max_web_results=5,
                auto_save=True,
            )
            result = await self.research_agent.research(request)

            return {
                "skipped": False,
                "query": query,
                "repos_found": len(result.repos_found),
                "skills_generated": len(result.skills_generated),
                "skills_saved": result.skills_saved,
                "errors": result.errors,
            }
        except Exception as e:
            logger.warning(f"[Spider] Research phase failed: {e}")
            return {"skipped": True, "reason": str(e)}

    # ── Phase 3: Agent Execution ──────────────────────────────────────

    async def run_analysis(
        self,
        project_path: str,
        mode: str = "quick",
    ) -> AsyncGenerator[dict, None]:
        """Esegue l'analisi completa con streaming del progresso.

        Yields:
            dict con chiavi: phase, progress, detail, report_chunk, done, error
        """
        t0 = time.time()
        mode = mode.lower()
        if mode not in ("quick", "deep", "full"):
            yield {"error": f"Modalita' non valida: {mode}. Usa quick/deep/full"}
            return

        # ── FASE 1: Discovery ──
        yield {"phase": "discovery", "progress": 5, "detail": "Scansione filesystem..."}

        try:
            dna = self.discover(project_path)
        except Exception as e:
            yield {"error": f"Discovery fallita: {e}"}
            return

        yield {
            "phase": "discovery",
            "progress": 20,
            "detail": f"Trovati {dna.total_files} file, {dna.total_loc:,} LOC, "
                      f"{len(dna.languages)} linguaggi, {len(dna.frameworks)} framework"
        }

        # ── FASE 1.5: Research (optional) ──
        if self.research_agent:
            yield {"phase": "research", "progress": 22, "detail": "Ricerca autonoma per colmare lacune KB..."}
            research_info = await self._run_research_phase(dna)
            if not research_info.get("skipped"):
                yield {
                    "phase": "research",
                    "progress": 24,
                    "detail": f"Research: {research_info.get('skills_generated', 0)} skill generate, "
                              f"{research_info.get('repos_found', 0)} repo analizzati"
                }

        # ── FASE 2: Skill Matching ──
        yield {"phase": "matching", "progress": 25, "detail": "Matching skill dalla Knowledge Base..."}

        tasks = await self.match_skills(dna)

        yield {
            "phase": "matching",
            "progress": 30,
            "detail": f"{len(tasks)} agenti specializzati attivati"
        }

        # ── FASE 3: Agent Execution ──
        profile = dna.to_profile_text()
        agent_reports: list[AgentReport] = []

        if mode == "quick":
            # Single mega-query
            yield {"phase": "analysis", "progress": 35, "detail": "Analisi unificata in corso..."}

            report = await self._run_quick(dna, tasks, profile)
            agent_reports = [report]

            yield {"phase": "analysis", "progress": 85, "detail": "Analisi completata"}

        elif mode == "deep":
            # Parallel agents
            total_tasks = len(tasks)
            yield {"phase": "analysis", "progress": 35, "detail": f"Lancio {total_tasks} agenti in parallelo..."}

            # Esegui in parallelo con progress updates
            async for progress_update in self._run_deep(dna, tasks, profile):
                if "report" in progress_update:
                    agent_reports.append(progress_update["report"])
                    done_count = len(agent_reports)
                    pct = 35 + int((done_count / total_tasks) * 45)
                    yield {
                        "phase": "analysis",
                        "progress": pct,
                        "detail": f"[{done_count}/{total_tasks}] {progress_update['report'].agent_name} completato"
                    }

        elif mode == "full":
            # Parallel + cross-reference + board
            total_tasks = len(tasks)
            yield {"phase": "analysis", "progress": 35, "detail": f"Lancio {total_tasks} agenti in parallelo (Full Audit)..."}

            async for progress_update in self._run_deep(dna, tasks, profile):
                if "report" in progress_update:
                    agent_reports.append(progress_update["report"])
                    done_count = len(agent_reports)
                    pct = 35 + int((done_count / total_tasks) * 35)
                    yield {
                        "phase": "analysis",
                        "progress": pct,
                        "detail": f"[{done_count}/{total_tasks}] {progress_update['report'].agent_name} completato"
                    }

            # Cross-reference phase
            yield {"phase": "cross-ref", "progress": 75, "detail": "Cross-reference tra agenti..."}

        # ── FASE 4: Synthesis ──
        yield {"phase": "synthesis", "progress": 85, "detail": "Generazione report finale..."}

        # Calcola health score
        total_issues = sum(r.issues_found for r in agent_reports)
        high_issues = sum(r.severity_high for r in agent_reports)
        medium_issues = sum(r.severity_medium for r in agent_reports)
        health = max(0, 100 - (high_issues * 15) - (medium_issues * 5) - (total_issues * 1))

        # Genera sintesi finale
        synthesis = await self._generate_synthesis(dna, agent_reports, health, mode)

        elapsed = time.time() - t0

        # Componi il report Markdown completo
        markdown = self._compose_markdown_report(
            dna, agent_reports, synthesis, health, total_issues, mode, elapsed
        )

        yield {"phase": "synthesis", "progress": 95, "detail": "Report completo generato"}
        yield {
            "phase": "done",
            "progress": 100,
            "detail": f"Analisi completata in {elapsed:.0f}s — Health Score: {health}/100",
            "report_markdown": markdown,
            "health_score": health,
            "total_issues": total_issues,
            "agents_used": len(agent_reports),
            "done": True,
        }

    # ── Quick Mode: Single mega-query ─────────────────────────────────

    async def _run_quick(self, dna: ProjectDNA, tasks: list[AgentTask], profile: str) -> AgentReport:
        """Una singola query LLM con tutto il contesto unificato."""
        t0 = time.time()

        # Costruisci mega-prompt
        agent_sections = "\n\n".join(
            f"## {t.agent_name} ({t.domain.upper()})\n{t.prompt}"
            for t in tasks
        )
        kb_context = "\n".join(t.context for t in tasks if t.context)

        system = (
            "Sei Spider Analysis di Noxen — un sistema di audit autonomo.\n"
            "Stai analizzando un progetto software. Esegui TUTTI i ruoli degli agenti elencati.\n"
            "Per ogni area genera un report strutturato con issue trovate e fix consigliate.\n"
            "Alla fine genera un RIEPILOGO con health score 0-100 e top 10 azioni.\n\n"
            f"PROFILO PROGETTO:\n{profile}\n\n"
            f"AGENTI DA IMPERSONARE:\n{agent_sections}"
        )

        if kb_context:
            system += f"\n\n{kb_context}"

        messages = [{"role": "user", "content": "Esegui l'analisi completa del progetto. Sii dettagliato e specifico."}]

        # Query LLM
        content = ""
        try:
            async for token in self.llm.stream_query(messages, system):
                content += token
        except Exception as e:
            content = f"Errore durante l'analisi: {e}"

        elapsed_ms = int((time.time() - t0) * 1000)

        # Parse approssimativo per conteggio issue
        issues = content.lower().count("critico") + content.lower().count("alto") + \
                 content.lower().count("medio") + content.lower().count("basso")

        return AgentReport(
            agent_name="Spider Quick Analysis",
            domain="all",
            content=content,
            issues_found=issues,
            severity_high=content.lower().count("critico") + content.lower().count("alto"),
            severity_medium=content.lower().count("medio"),
            severity_low=content.lower().count("basso"),
            latency_ms=elapsed_ms,
        )

    # ── Deep Mode: Parallel agents ────────────────────────────────────

    async def _run_deep(
        self, dna: ProjectDNA, tasks: list[AgentTask], profile: str
    ) -> AsyncGenerator[dict, None]:
        """N query LLM con concorrenza controllata (Semaphore).

        Ollama locale processa ~1 query alla volta, quindi lanciare 8 agenti
        in parallelo causa timeout. Usiamo un semaforo per limitare a
        MAX_CONCURRENT agenti simultanei, con timeout per-agente generoso.
        Per provider locali (Ollama) usiamo concorrenza 1 e timeout lungo.
        Per provider cloud (Gemini/Claude/OpenAI) parallelismo pieno.
        """
        # Rileva se il provider e' locale o cloud
        provider_name = getattr(self.llm, 'active_provider', '') or ''
        is_local = provider_name.lower() in ('ollama', 'local', '')

        if is_local:
            MAX_CONCURRENT = 1       # sequenziale — Ollama serve 1 alla volta
            AGENT_TIMEOUT = 600      # 10 min per agente (modelli locali lenti)
        else:
            MAX_CONCURRENT = 4       # cloud API gestisce parallelismo
            AGENT_TIMEOUT = 180      # 3 min bastano per cloud

        logger.info(f"[Spider] Concorrenza: {MAX_CONCURRENT}, timeout: {AGENT_TIMEOUT}s (provider: {provider_name or 'unknown'})")
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def run_single_agent(task: AgentTask) -> AgentReport:
            async with sem:
                t0 = time.time()
                logger.info(f"[Spider] ▶ Avvio agente: {task.agent_name}")
                system = (
                    f"Sei {task.agent_name}, un agente specializzato di Spider Analysis (Noxen).\n"
                    f"Stai analizzando un progetto. Il tuo dominio e': {task.domain}\n\n"
                    f"PROFILO PROGETTO:\n{profile}\n\n"
                    f"IL TUO COMPITO:\n{task.prompt}"
                )
                if task.context:
                    system += f"\n\n{task.context}"

                messages = [{"role": "user", "content": (
                    "Esegui la tua analisi specializzata. Sii specifico e concreto.\n"
                    "Per ogni issue indica: SEVERITA' (CRITICO/ALTO/MEDIO/BASSO), descrizione, fix."
                )}]

                content = ""
                try:
                    async for token in self.llm.stream_query(messages, system):
                        content += token
                except asyncio.TimeoutError:
                    content = f"Timeout agente {task.agent_name} dopo {AGENT_TIMEOUT}s"
                    logger.warning(f"[Spider] ⏱ Timeout: {task.agent_name}")
                except Exception as e:
                    content = f"Errore agente {task.agent_name}: {e}"
                    logger.error(f"[Spider] ✗ Errore {task.agent_name}: {e}")

                elapsed_ms = int((time.time() - t0) * 1000)
                logger.info(f"[Spider] ✓ {task.agent_name} completato in {elapsed_ms}ms")
                cl = content.lower()

                return AgentReport(
                    agent_name=task.agent_name,
                    domain=task.domain,
                    content=content,
                    issues_found=cl.count("critico") + cl.count("alto") + cl.count("medio") + cl.count("basso"),
                    severity_high=cl.count("critico") + cl.count("alto"),
                    severity_medium=cl.count("medio"),
                    severity_low=cl.count("basso"),
                    latency_ms=elapsed_ms,
                )

        # Lancia tutti — il semaforo dentro run_single_agent controlla la concorrenza
        # Niente wait_for esterno: il timeout e' gestito internamente per non
        # contare il tempo di attesa in coda al semaforo
        pending = [asyncio.ensure_future(run_single_agent(task)) for task in tasks]

        for future in asyncio.as_completed(pending):
            report = await future
            yield {"report": report}

    # ── Synthesis ─────────────────────────────────────────────────────

    async def _generate_synthesis(
        self, dna: ProjectDNA, reports: list[AgentReport], health: int, mode: str
    ) -> str:
        """Genera la sintesi finale combinando tutti i report degli agenti."""
        profile = dna.to_profile_text()

        # Per quick mode, il report e' gia' unificato
        if mode == "quick" and reports:
            return reports[0].content

        # Per deep/full, sintetizza
        reports_text = ""
        for r in reports:
            reports_text += f"\n\n{'='*60}\n"
            reports_text += f"AGENTE: {r.agent_name} ({r.domain})\n"
            reports_text += f"Issue trovate: {r.issues_found} (H:{r.severity_high} M:{r.severity_medium} L:{r.severity_low})\n"
            reports_text += f"{'='*60}\n"
            # Limita per non sforare context window
            reports_text += r.content[:3000]

        system = (
            "Sei il Chief Architect di Spider Analysis (Noxen).\n"
            "Hai ricevuto i report da tutti gli agenti specializzati.\n"
            "Genera una SINTESI ESECUTIVA:\n"
            "1. Health Score motivato (attuale: " + str(health) + "/100)\n"
            "2. Top 10 issue per priorita' (cross-referencing tra agenti)\n"
            "3. Pattern ricorrenti\n"
            "4. Roadmap azioni consigliate (cosa fare prima, cosa dopo)\n"
            "5. Punti di forza del progetto\n\n"
            f"PROFILO:\n{profile}\n\n"
            f"REPORT AGENTI:\n{reports_text}"
        )

        messages = [{"role": "user", "content": "Genera la sintesi esecutiva completa."}]

        content = ""
        try:
            async for token in self.llm.stream_query(messages, system):
                content += token
        except Exception as e:
            content = f"Errore sintesi: {e}"

        return content

    # ── Markdown Report ───────────────────────────────────────────────

    def _compose_markdown_report(
        self,
        dna: ProjectDNA,
        reports: list[AgentReport],
        synthesis: str,
        health: int,
        total_issues: int,
        mode: str,
        elapsed: float,
    ) -> str:
        """Componi il report Markdown completo esportabile."""
        mode_label = {"quick": "Quick Scan", "deep": "Deep Analysis", "full": "Full Audit"}

        md = []
        md.append(f"# Spider Analysis Report — {dna.name}")
        md.append(f"")
        md.append(f"> Generato da Noxen Spider | Modalita': **{mode_label.get(mode, mode)}** | Tempo: {elapsed:.0f}s")
        md.append(f"")

        # Health Score badge
        health_emoji = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        md.append(f"## {health_emoji} Health Score: {health}/100")
        md.append(f"")
        md.append(f"| Metrica | Valore |")
        md.append(f"|---|---|")
        md.append(f"| Issues totali | {total_issues} |")
        md.append(f"| Agenti eseguiti | {len(reports)} |")
        md.append(f"| File analizzati | {dna.total_files} |")
        md.append(f"| LOC totali | {dna.total_loc:,} |")
        md.append(f"| Linguaggi | {', '.join(dna.languages) or 'N/A'} |")
        md.append(f"| Framework | {', '.join(dna.frameworks) or 'N/A'} |")
        md.append(f"| Database | {dna.db_type or 'Non rilevato'} |")
        md.append(f"| Docker | {'Si' if dna.has_docker else 'No'} |")
        md.append(f"| CI/CD | {'Si' if dna.has_ci else 'No'} |")
        md.append(f"| Test | {'Si' if dna.has_tests else 'No'} |")
        md.append(f"| API Endpoints | ~{dna.api_endpoints_estimate} |")
        md.append(f"")

        # DNA / Struttura
        md.append(f"## Struttura Progetto")
        md.append(f"```")
        md.append(dna.structure_tree or "(non disponibile)")
        md.append(f"```")
        md.append(f"")

        if dna.loc_by_lang:
            md.append(f"### LOC per Linguaggio")
            md.append(f"| Linguaggio | Righe |")
            md.append(f"|---|---|")
            for lang, loc in sorted(dna.loc_by_lang.items(), key=lambda x: -x[1])[:10]:
                md.append(f"| {lang} | {loc:,} |")
            md.append(f"")

        # Sintesi Esecutiva
        if mode != "quick":
            md.append(f"## Sintesi Esecutiva")
            md.append(f"")
            md.append(synthesis)
            md.append(f"")

        # Report per Agente
        md.append(f"---")
        md.append(f"")
        md.append(f"## Report Dettagliati per Agente")
        md.append(f"")

        for r in reports:
            severity_badge = ""
            if r.severity_high > 0:
                severity_badge = f" 🔴 {r.severity_high} critici/alti"
            if r.severity_medium > 0:
                severity_badge += f" 🟡 {r.severity_medium} medi"

            md.append(f"### {r.agent_name} ({r.domain})")
            md.append(f"*{r.issues_found} issue trovate{severity_badge} — {r.latency_ms}ms*")
            md.append(f"")
            md.append(r.content)
            md.append(f"")
            md.append(f"---")
            md.append(f"")

        # Footer
        md.append(f"*Report generato da Noxen Spider Analysis v0.2.0*")

        return "\n".join(md)

    # ── Helpers Discovery ─────────────────────────────────────────────

    def _detect_frameworks(self, config_file: Path, dna: ProjectDNA) -> None:
        """Rileva framework dal contenuto di un file di configurazione."""
        try:
            content = config_file.read_text(errors="ignore")
            for fw_name, patterns in FRAMEWORK_DETECT.items():
                for pattern in patterns:
                    if pattern in content:
                        dna.frameworks.append(fw_name)
                        break
        except Exception:
            pass

    def _detect_database(self, root: Path, files: list[Path]) -> tuple[bool, str]:
        """Rileva tipo di database dal progetto."""
        db_indicators = {
            "MySQL": ["mysql", "mariadb", "DB_CONNECTION=mysql"],
            "PostgreSQL": ["postgres", "psycopg", "DB_CONNECTION=pgsql"],
            "MongoDB": ["mongodb", "mongoose", "mongo"],
            "SQLite": ["sqlite", "DB_CONNECTION=sqlite"],
            "Redis": ["redis", "ioredis"],
            "Elasticsearch": ["elasticsearch", "elastic"],
        }

        # Cerca in file di configurazione
        for f in files:
            if f.name in (".env", ".env.example", "docker-compose.yml", "docker-compose.yaml",
                          "composer.json", "package.json", "requirements.txt", "Gemfile"):
                try:
                    content = f.read_text(errors="ignore").lower()
                    for db_name, patterns in db_indicators.items():
                        if any(p in content for p in patterns):
                            return True, db_name
                except Exception:
                    pass

        return False, ""

    def _extract_env_keys(self, env_file: Path, dna: ProjectDNA) -> None:
        """Estrai i nomi delle variabili d'ambiente (senza i valori)."""
        try:
            for line in env_file.read_text(errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key = line.split("=", 1)[0].strip()
                    if key and key not in dna.env_vars:
                        dna.env_vars.append(key)
        except Exception:
            pass

    def _generate_tree(self, root: Path, max_depth: int = 2) -> str:
        """Genera una struttura ad albero ASCII della directory."""
        lines = [root.name + "/"]

        def _walk(path: Path, prefix: str, depth: int):
            if depth >= max_depth:
                return
            try:
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            except PermissionError:
                return

            # Filtra
            entries = [e for e in entries if e.name not in SKIP_DIRS
                       and not e.name.startswith(".")]

            for i, entry in enumerate(entries[:25]):  # Max 25 per livello
                is_last = (i == len(entries[:25]) - 1)
                connector = "└── " if is_last else "├── "
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{prefix}{connector}{entry.name}{suffix}")

                if entry.is_dir():
                    extension = "    " if is_last else "│   "
                    _walk(entry, prefix + extension, depth + 1)

            if len(entries) > 25:
                lines.append(f"{prefix}└── ... ({len(entries) - 25} altri)")

        _walk(root, "", 0)
        return "\n".join(lines[:100])  # Max 100 righe

    def _find_key_files(self, root: Path, files: list[Path]) -> list[str]:
        """Trova i file piu' importanti del progetto."""
        key_patterns = [
            "README.md", "CHANGELOG.md", "LICENSE",
            "Dockerfile", "docker-compose.yml",
            "Makefile", ".env.example",
            "package.json", "composer.json", "requirements.txt",
            "pyproject.toml", "Cargo.toml", "go.mod",
        ]
        found = []
        for f in files:
            rel = str(f.relative_to(root))
            if f.name in key_patterns or rel in key_patterns:
                found.append(rel)
        return sorted(found)[:20]
