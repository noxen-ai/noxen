# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Noxen. See LICENSE for details.
"""Noxen - Orchestration Engine.

Il cervello del sistema. Coordina:
  - AutoDiscovery (scansione microservizi)
  - DBConnector (schema + query read-only)
  - Ingestor (indicizzazione RAG)
  - PluginComposer (skill Claude Code)
  - LLMProvider (multi-backend + board CDA)
  - ContextGatherer (raccolta contesto multi-source)
  - SkillRouter (selezione skill rilevanti per la query)
  - EventRouter (logging eventi su Qdrant)

Workflow:
  1. init() — scansiona progetto, indicizza, connetti DB
  2. query() — ricevi domanda, raccogli contesto, chiedi al LLM
  3. loop() — analizza + istruisci Claude Code in ciclo

Phase 2 Refactor: logica di contesto e routing estratta in componenti dedicati.
"""

from __future__ import annotations

import asyncio
import json
from core.logger import get_logger
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import settings
from .auto_discovery import AutoDiscovery, EcosystemMap
from .claude_skill_parser import parse_plugin_repo, ClaudeSkill
from .db_connector import DBConnector, SchemaInfo
from .llm_provider import LLMProvider, LLMResponse, BoardResponse

logger = get_logger("noxen.orchestrator")


@dataclass
class OrchestratorState:
    """Stato corrente dell'orchestratore."""
    initialized: bool = False
    project_path: str = ""
    ecosystem: EcosystemMap | None = None
    db_connected: bool = False
    db_schema: SchemaInfo | None = None
    indexed_services: list[str] = field(default_factory=list)
    available_skills: int = 0
    active_provider: str = ""
    available_providers: list[str] = field(default_factory=list)
    llm_mode: str = "single"

    def to_dict(self) -> dict:
        return {
            "initialized": self.initialized,
            "project_path": self.project_path,
            "total_services": self.ecosystem.total_services if self.ecosystem else 0,
            "languages": self.ecosystem.languages if self.ecosystem else [],
            "frameworks": self.ecosystem.frameworks if self.ecosystem else [],
            "db_connected": self.db_connected,
            "db_tables": self.db_schema.total_tables if self.db_schema else 0,
            "indexed_services": self.indexed_services,
            "available_skills": self.available_skills,
            "active_provider": self.active_provider,
            "available_providers": self.available_providers,
            "llm_mode": self.llm_mode,
        }


class Orchestrator:
    """Motore di orchestrazione Noxen.

    Phase 2: logica di context gathering e skill routing estratta in componenti dedicati.
    L'interfaccia pubblica è invariata per backward compatibility.
    """

    def __init__(
        self,
        llm: LLMProvider,
        ingestor: Any = None,
        project_manager: Any = None,
        plugin_composer: Any = None,
        knowledge_base: Any = None,
        context_gatherer: Any = None,
        skill_router: Any = None,
        event_router: Any = None,
    ) -> None:
        self.llm = llm
        self.ingestor = ingestor
        self.project_manager = project_manager
        self.plugin_composer = plugin_composer
        self.knowledge_base = knowledge_base
        self.discovery: AutoDiscovery | None = None
        self.db: DBConnector | None = None
        self.state = OrchestratorState()

        # Phase 2: componenti estratti
        self.context_gatherer = context_gatherer
        self.skill_router = skill_router
        self.event_router = event_router

        # Legacy: _skills_cache per backward compat (delegato a skill_router)
        self._skills_cache: list[dict] = []

    # ── Init ─────────────────────────────────────────────────────────

    async def init_project(self, project_path: str) -> dict[str, Any]:
        """Inizializza l'orchestratore su un progetto.

        1. AutoDiscovery — scansiona microservizi
        2. DB Connection — connetti e leggi schema
        3. Indexing — indicizza tutto in Qdrant
        4. Skills — carica skill disponibili
        """
        root = Path(project_path).expanduser().resolve()
        if not root.is_dir():
            return {"error": f"Directory non trovata: {root}"}

        logger.info(f"=== INIT PROGETTO: {root} ===")
        results: dict[str, Any] = {"project": str(root)}

        # Emit event
        if self.event_router:
            await self.event_router.emit("init", {"project_path": str(root)}, source="orchestrator")

        # 1. AutoDiscovery
        logger.info("[1/4] AutoDiscovery...")
        self.discovery = AutoDiscovery(root)
        ecosystem = self.discovery.scan()
        self.discovery.save_map(settings.data_dir)
        self.state.ecosystem = ecosystem
        self.state.project_path = str(root)
        results["discovery"] = {
            "services": ecosystem.total_services,
            "languages": ecosystem.languages,
            "frameworks": ecosystem.frameworks,
        }

        # 2. DB Connection
        logger.info("[2/4] Database connection...")
        db_connected = False
        for svc in ecosystem.services:
            if svc.has_db and svc.db_config:
                cfg = svc.db_config
                self.db = DBConnector(
                    host=cfg.get("host", settings.mysql_host),
                    port=int(cfg.get("port", settings.mysql_port)),
                    user=cfg.get("user", settings.mysql_user),
                    password=cfg.get("password", settings.mysql_password),
                    database=cfg.get("database", settings.mysql_database),
                )
                db_connected = await self.db.connect()
                if db_connected:
                    self.state.db_schema = await self.db.get_schema()
                    break

        # Fallback: usa settings se nessun .env trovato
        if not db_connected and settings.mysql_database:
            self.db = DBConnector(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                database=settings.mysql_database,
            )
            db_connected = await self.db.connect()
            if db_connected:
                self.state.db_schema = await self.db.get_schema()

        self.state.db_connected = db_connected
        results["database"] = {
            "connected": db_connected,
            "tables": self.state.db_schema.total_tables if self.state.db_schema else 0,
        }

        # 3. Indexing
        logger.info("[3/4] Indicizzazione servizi...")
        indexed = []
        if self.project_manager and self.ingestor:
            for svc in ecosystem.services:
                try:
                    # Registra come progetto
                    proj = self.project_manager.register(svc.name, svc.path)
                    # Avvia indicizzazione
                    task_id = self.ingestor.start_indexing(svc.name)
                    indexed.append(svc.name)
                    logger.info(f"  Indicizzazione avviata: {svc.name} (task: {task_id})")
                except Exception as e:
                    logger.warning(f"  Indicizzazione fallita per {svc.name}: {e}")

            # Indicizza anche lo schema DB come contesto
            if self.state.db_schema and self.db:
                schema_text = self.db.schema_to_text(self.state.db_schema)
                try:
                    proj = self.project_manager.register("_db_schema", str(root))
                    # Salva schema come file temporaneo e indicizza
                    schema_file = settings.data_dir / "db_schema_context.txt"
                    schema_file.write_text(schema_text)
                    logger.info("  Schema DB indicizzato come contesto")
                except Exception as e:
                    logger.warning(f"  Indicizzazione schema fallita: {e}")

        self.state.indexed_services = indexed
        results["indexing"] = {"services_queued": len(indexed)}

        # 4. Skills
        logger.info("[4/4] Caricamento skills Claude Code...")
        if self.plugin_composer:
            self.plugin_composer.scan_all()
            # Aggiorna sia _skills_cache (legacy) sia skill_router
            self._skills_cache = self.plugin_composer.get_all_skills()
            if self.skill_router:
                self.skill_router.refresh_cache()
            self.state.available_skills = len(self._skills_cache)
        results["skills"] = {"available": self.state.available_skills}

        # Stato provider
        self.state.active_provider = settings.active_provider
        self.state.available_providers = self.llm.available_providers
        self.state.llm_mode = settings.llm_mode
        self.state.initialized = True

        # Sincronizza stato con ContextGatherer
        self._sync_context_gatherer()

        logger.info(f"=== INIT COMPLETATO ===")
        logger.info(f"  Servizi: {ecosystem.total_services}")
        logger.info(f"  DB: {'connesso' if db_connected else 'non connesso'}")
        logger.info(f"  Indicizzazione: {len(indexed)} servizi in coda")
        logger.info(f"  Skills: {self.state.available_skills}")
        logger.info(f"  LLM: {settings.active_provider} ({settings.llm_mode})")

        return results

    # ── Context Gathering (delegato) ─────────────────────────────────

    async def _gather_context(self, question: str, service: str = "", use_db: bool = True) -> dict[str, Any]:
        """Raccoglie contesto — delega a ContextGatherer se disponibile."""
        if self.context_gatherer:
            return await self.context_gatherer.gather(question, service, use_db)

        # Fallback legacy (non dovrebbe mai servire in produzione)
        return {
            "system_prompt": self._build_system_prompt("", "", "", ""),
            "kb_results": 0,
            "rag_results": 0,
            "db_active": False,
            "skills_matched": 0,
        }

    # ── Query (non-streaming) ─────────────────────────────────────────

    async def query(
        self,
        question: str,
        service: str = "",
        use_db: bool = True,
        mode: str = "",
    ) -> dict[str, Any]:
        """Processa una domanda con contesto completo (non-streaming).

        Funziona SEMPRE — anche senza init_project().
        """
        mode = mode or settings.llm_mode

        # Emit event
        if self.event_router:
            await self.event_router.emit("query", {"question": question[:200], "mode": mode}, source="orchestrator")

        ctx = await self._gather_context(question, service, use_db)
        system = ctx["system_prompt"]

        if mode == "board":
            board_result = await self.llm.board_query(question, system)
            return {
                "mode": "board",
                "synthesis": board_result.synthesis,
                "chairman": board_result.chairman,
                "consensus": board_result.consensus_level,
                "responses": [
                    {
                        "provider": r.provider,
                        "model": r.model,
                        "content": r.content,
                        "latency_ms": r.latency_ms,
                        "tokens": r.tokens_in + r.tokens_out,
                        "error": r.error,
                    }
                    for r in board_result.responses
                ],
                "latency_ms": board_result.latency_ms,
                "context_used": {
                    "kb_results": ctx["kb_results"],
                    "rag_results": ctx["rag_results"],
                    "db_schema": ctx["db_active"],
                    "skills_matched": ctx["skills_matched"],
                },
            }
        else:
            result = await self.llm.query(question, system)
            return {
                "mode": "single",
                "provider": result.provider,
                "model": result.model,
                "content": result.content,
                "latency_ms": result.latency_ms,
                "tokens": result.tokens_in + result.tokens_out,
                "error": result.error,
                "context_used": {
                    "kb_results": ctx["kb_results"],
                    "rag_results": ctx["rag_results"],
                    "db_schema": ctx["db_active"],
                    "skills_matched": ctx["skills_matched"],
                },
            }

    # ── Streaming Query ───────────────────────────────────────────────

    async def stream_query(
        self,
        messages: list[dict[str, str]],
        service: str = "",
        use_db: bool = True,
    ):
        """Streaming query con contesto completo.

        Funziona SEMPRE — anche senza init_project().

        Args:
            messages: Chat history [{"role": "user"|"assistant", "content": "..."}]
            service: Filtra RAG su un servizio specifico
            use_db: Includi contesto DB se disponibile

        Yields:
            str: Token della risposta in streaming
        """
        # Prendi l'ultima domanda per il context gathering
        last_question = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_question = m["content"]
                break

        if not last_question:
            yield "[ERROR] Nessun messaggio utente trovato"
            return

        ctx = await self._gather_context(last_question, service, use_db)
        system = ctx["system_prompt"]

        logger.info(
            f"[stream] context: kb={ctx['kb_results']}, rag={ctx['rag_results']}, "
            f"db={ctx['db_active']}, skills={ctx['skills_matched']}"
        )

        async for token in self.llm.stream_query(messages, system):
            yield token

    # ── DB Query ─────────────────────────────────────────────────────

    async def db_query(self, sql: str) -> list[dict]:
        """Esegui una query SQL read-only."""
        if not self.db or not self.state.db_connected:
            return [{"error": "Database non connesso"}]

        if self.event_router:
            await self.event_router.emit("db", {"sql": sql[:200]}, source="orchestrator")

        return await self.db.query(sql)

    # ── Loop Controller ──────────────────────────────────────────────

    async def analyze_and_instruct(self, task: str) -> dict[str, Any]:
        """Analizza il progetto e genera istruzioni per Claude Code.

        Questo e' il cuore del loop Noxen -> Claude Code:
        1. Analizza il task con contesto completo
        2. Il LLM (o il board) genera istruzioni precise
        3. Le istruzioni vengono ritornate pronte per l'esecuzione
        """
        analysis_prompt = (
            f"Sei l'orchestratore di Noxen. Il tuo ruolo e' analizzare e dare istruzioni "
            f"precise a Claude Code per eseguire modifiche.\n\n"
            f"TASK: {task}\n\n"
            f"Genera istruzioni dettagliate e precise per Claude Code:\n"
            f"1. Quali file modificare e come\n"
            f"2. Quale codice scrivere\n"
            f"3. Quali comandi eseguire\n"
            f"4. Come verificare che funziona\n\n"
            f"Rispondi in formato strutturato con le istruzioni esatte."
        )

        result = await self.query(analysis_prompt, mode=settings.llm_mode)

        # Wrap come istruzione per Claude Code
        content = result.get("synthesis") or result.get("content", "")
        return {
            "task": task,
            "instructions": content,
            "mode": result.get("mode"),
            "consensus": result.get("consensus", ""),
            "claude_code_command": f"Esegui queste istruzioni:\n\n{content}",
        }

    # ── Internal ─────────────────────────────────────────────────────

    def _sync_context_gatherer(self) -> None:
        """Sincronizza lo stato dell'Orchestrator con il ContextGatherer."""
        if not self.context_gatherer:
            return
        self.context_gatherer.db = self.db
        self.context_gatherer.db_schema = self.state.db_schema
        self.context_gatherer.ecosystem = self.state.ecosystem
        self.context_gatherer.initialized = self.state.initialized

    def _build_system_prompt(self, kb: str, rag: str, db: str, skills: str) -> str:
        """Fallback: costruisci il system prompt (legacy, usato solo se no context_gatherer)."""
        parts = [
            "Sei Noxen, un AI orchestrator per ecosistemi multi-microservizi.",
            "Analizza il codice, il database e le architetture con precisione.",
            "Usa la conoscenza interna (skills, agenti, documentazione) per rispondere con competenza specializzata.",
            "Rispondi in italiano. Cita sempre le fonti specifiche.",
        ]

        if self.state.ecosystem:
            eco = self.state.ecosystem
            parts.append(
                f"\nECOSISTEMA: {eco.total_services} microservizi, "
                f"linguaggi: {', '.join(eco.languages)}, "
                f"framework: {', '.join(eco.frameworks)}"
            )

        if kb:
            parts.append(f"\n{kb}")
        if rag:
            parts.append(f"\n{rag}")
        if db:
            parts.append(f"\n{db}")
        if skills:
            parts.append(f"\n{skills}")

        return "\n".join(parts)
