"""API Routes: Orchestrator Unificato + Settings.

L'Orchestrator e' l'UNICO punto di contatto per l'utente.
Funziona SEMPRE — anche senza init_project():
  - Knowledge Base (15K docs) → sempre disponibile
  - Codebase RAG → solo dopo init_project()
  - DB Schema → solo dopo init_project() con DB
  - Skills → sempre disponibili

Endpoint principali:
  POST /api/orchestrator/chat     → Chat streaming (punto di ingresso principale)
  POST /api/orchestrator/query    → Query non-streaming (backward compat)
  POST /api/orchestrator/init     → Init su un progetto specifico
  GET  /api/orchestrator/status   → Stato corrente
"""

import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings
from core.llm_provider import LLMProvider
from core.orchestrator import Orchestrator
from core.spider import SpiderAnalysis
from core.neural_engine import NeuralEngine
from core.execution.engine import ExecutionEngine, EngineConfig
from core.tenants.auth import TenantContext, get_tenant_context

router = APIRouter(tags=["orchestrator"])

_orchestrator: Orchestrator | None = None
_llm: LLMProvider | None = None


def init_router(orchestrator: Orchestrator, llm: LLMProvider) -> None:
    global _orchestrator, _llm
    _orchestrator = orchestrator
    _llm = llm


def _get() -> Orchestrator:
    if not _orchestrator:
        raise HTTPException(503, "Orchestrator non inizializzato")
    return _orchestrator


# ── Chat Unificata (streaming) ───────────────────────────────────────

class ChatMessage(BaseModel):
    role: str       # "user" o "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    service: str = ""      # Filtra RAG su un servizio
    use_db: bool = True
    stream: bool = True


@router.post("/api/orchestrator/chat")
async def orchestrator_chat(
    req: ChatRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Chat unificata con l'Orchestratore (streaming).

    L'unico punto di contatto per l'utente. Raccoglie automaticamente:
    - Knowledge Base (skills, agents, docs — 15K documenti)
    - Codebase RAG (se init_project() e' stato chiamato)
    - Schema DB (se connesso e query e' pertinente)
    - Skill routing (competenze specifiche)

    Funziona SEMPRE, anche senza init_project().
    """
    orch = _get()

    # Costruisci messages con history + nuovo messaggio
    messages = [{"role": m.role, "content": m.content} for m in req.history[-20:]]
    messages.append({"role": "user", "content": req.message})

    if req.stream:
        async def generate():
            try:
                async for token in orch.stream_query(messages, req.service, req.use_db):
                    # SSE format
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        # Non-streaming: usa query() classico
        result = await orch.query(req.message, req.service, req.use_db)
        return result


# ── Query non-streaming (backward compat) ────────────────────────────

class QueryRequest(BaseModel):
    question: str
    service: str = ""     # Vuoto = cross-service
    use_db: bool = True
    mode: str = ""        # "single" o "board", vuoto = usa default


@router.post("/api/orchestrator/query")
async def orchestrator_query(
    req: QueryRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Query intelligente con contesto completo (non-streaming).

    Funziona SEMPRE — anche senza init_project().
    """
    orch = _get()
    return await orch.query(req.question, req.service, req.use_db, req.mode)


# ── Init Progetto ────────────────────────────────────────────────────

class InitRequest(BaseModel):
    project_path: str


@router.post("/api/orchestrator/init")
async def init_project(req: InitRequest):
    """Inizializza l'orchestratore su un progetto (scan + index + DB).

    Opzionale — aggiunge contesto codebase + DB alla Knowledge Base.
    """
    return await _get().init_project(req.project_path)


# ── Status ───────────────────────────────────────────────────────────

@router.get("/api/orchestrator/status")
async def get_status():
    """Stato corrente dell'orchestratore."""
    orch = _get()
    base = orch.state.to_dict()
    # Aggiungi info knowledge base
    if orch.knowledge_base:
        try:
            kb_stats = orch.knowledge_base.get_stats()
            base["knowledge_base"] = {
                "total_chunks": kb_stats.get("total_chunks", 0),
                "has_data": kb_stats.get("has_data", False),
                "status": kb_stats.get("status", "unknown"),
            }
        except Exception:
            base["knowledge_base"] = {"total_chunks": 0, "has_data": False}
    return base


# ── DB Query ─────────────────────────────────────────────────────────

class DBQueryRequest(BaseModel):
    sql: str


@router.post("/api/orchestrator/db-query")
async def db_query(req: DBQueryRequest):
    """Esegui query SQL read-only."""
    orch = _get()
    if not orch.state.db_connected:
        raise HTTPException(400, "Database non connesso")
    rows = await orch.db_query(req.sql)
    return {"rows": rows, "count": len(rows)}


# ── Analyze & Instruct ──────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str


@router.post("/api/orchestrator/analyze")
async def analyze_and_instruct(req: TaskRequest):
    """Analizza e genera istruzioni per Claude Code."""
    orch = _get()
    return await orch.analyze_and_instruct(req.task)


# ── Spider Analysis ──────────────────────────────────────────────────

class SpiderRequest(BaseModel):
    project_path: str
    mode: str = "quick"    # quick, deep, full


@router.post("/api/orchestrator/spider")
async def spider_analysis(req: SpiderRequest):
    """Spider Analysis — analisi autonoma di un progetto.

    Streaming SSE del progresso + report finale.
    Modalita':
      - quick: 1 query LLM unificata (1-2 min)
      - deep:  N agenti paralleli (5-10 min)
      - full:  N agenti + cross-ref + board synthesis (15-30 min)
    """
    orch = _get()
    spider = SpiderAnalysis(orch, orch.knowledge_base)

    async def generate():
        try:
            async for update in spider.run_analysis(req.project_path, req.mode):
                yield f"data: {json.dumps(update, default=str)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Neural Development Engine ────────────────────────────────────────

_engine: NeuralEngine | None = None


class EngineRequest(BaseModel):
    project_path: str


@router.post("/api/orchestrator/engine/start")
async def engine_start(req: EngineRequest):
    """Avvia il Neural Development Engine (loop autonomo completo)."""
    global _engine
    orch = _get()
    _engine = NeuralEngine(orch, orch.knowledge_base)

    async def generate():
        try:
            async for update in _engine.run(req.project_path):
                yield f"data: {json.dumps(update, default=str)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'phase': 'error', 'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/orchestrator/engine/stop")
async def engine_stop():
    """Richiedi stop graceful del Neural Engine."""
    global _engine
    if _engine:
        _engine.request_stop()
        return {"status": "stop_requested"}
    return {"status": "not_running"}


@router.get("/api/orchestrator/engine/status")
async def engine_status():
    """Stato corrente del Neural Engine."""
    global _engine
    if _engine and _engine.state:
        from dataclasses import asdict
        return {
            "running": _engine.state.is_running,
            "state": asdict(_engine.state),
            "goals": [asdict(g) for g in _engine.goals],
        }
    return {"running": False, "state": None, "goals": []}


# ── New Execution Engine (Phase 4) ──────────────────────────────────

_execution_engine: ExecutionEngine | None = None


class ExecutionEngineRequest(BaseModel):
    project_path: str
    project_name: str = ""
    require_approval: bool = True
    goals: list[dict] | None = None


@router.post("/api/engine/start")
async def execution_engine_start(
    req: ExecutionEngineRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Avvia il nuovo Execution Engine (sandbox + DAG + approval gate)."""
    global _execution_engine
    orch = _get()

    # LLM query function
    async def llm_query(system: str, user_msg: str) -> str:
        messages = [{"role": "user", "content": user_msg}]
        content = ""
        try:
            async for token in orch.llm.stream_query(messages, system):
                content += token
        except Exception as e:
            content = f"[LLM Error: {e}]"
        return content

    config = EngineConfig(
        require_approval=req.require_approval,
        qdrant_persist=False,  # Safe default for now
    )

    _execution_engine = ExecutionEngine(
        llm_query_fn=llm_query,
        knowledge_base=orch.knowledge_base,
        event_router=getattr(orch, "event_router", None),
        config=config,
    )

    async def generate():
        try:
            async for update in _execution_engine.run(
                req.project_path,
                project_name=req.project_name,
                goals=req.goals,
            ):
                yield f"data: {json.dumps(update, default=str)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'phase': 'error', 'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/engine/approve")
async def execution_engine_approve():
    """Approva il piano dell'Execution Engine."""
    global _execution_engine
    if _execution_engine and _execution_engine.approve():
        return {"status": "approved"}
    return {"status": "no_approval_pending"}


@router.post("/api/engine/reject")
async def execution_engine_reject():
    """Rifiuta il piano dell'Execution Engine."""
    global _execution_engine
    if _execution_engine and _execution_engine.reject():
        return {"status": "rejected"}
    return {"status": "no_approval_pending"}


@router.post("/api/engine/stop")
async def execution_engine_stop():
    """Richiedi stop graceful dell'Execution Engine."""
    global _execution_engine
    if _execution_engine:
        _execution_engine.request_stop()
        return {"status": "stop_requested"}
    return {"status": "not_running"}


@router.get("/api/engine/status")
async def execution_engine_status():
    """Stato corrente dell'Execution Engine."""
    global _execution_engine
    if _execution_engine:
        return _execution_engine.get_status()
    return {"running": False, "state": None, "goals": None}


# ── Settings ─────────────────────────────────────────────────────────

class ProviderUpdate(BaseModel):
    provider: str          # ollama, gemini, claude, openai
    api_key: str = ""
    model: str = ""


class SettingsUpdate(BaseModel):
    llm_mode: str = ""           # single, board
    active_provider: str = ""    # ollama, gemini, claude, openai
    board_chairman: str = ""
    mysql_host: str = ""
    mysql_port: int = 0
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""


@router.get("/api/settings")
async def get_settings():
    """Ritorna le impostazioni correnti (senza api key in chiaro)."""
    return {
        "llm": {
            "mode": settings.llm_mode,
            "active_provider": settings.active_provider,
            "board_chairman": settings.board_chairman,
            "providers": {
                "ollama": {
                    "configured": bool(settings.ollama_base_url),
                    "url": settings.ollama_base_url,
                    "model": settings.default_model,
                },
                "gemini": {
                    "configured": bool(settings.gemini_api_key),
                    "model": settings.gemini_model,
                    "has_key": bool(settings.gemini_api_key),
                },
                "claude": {
                    "configured": bool(settings.claude_api_key),
                    "model": settings.claude_model,
                    "has_key": bool(settings.claude_api_key),
                },
                "openai": {
                    "configured": bool(settings.openai_api_key),
                    "model": settings.openai_model,
                    "has_key": bool(settings.openai_api_key),
                },
                "grok": {
                    "configured": bool(settings.grok_api_key),
                    "model": settings.grok_model,
                    "has_key": bool(settings.grok_api_key),
                },
                "mercury": {
                    "configured": bool(settings.mercury_api_key),
                    "model": settings.mercury_model,
                    "has_key": bool(settings.mercury_api_key),
                },
                "qwen": {
                    "configured": bool(settings.qwen_api_key),
                    "model": settings.qwen_model,
                    "has_key": bool(settings.qwen_api_key),
                },
            },
        },
        "mysql": {
            "host": settings.mysql_host,
            "port": settings.mysql_port,
            "user": settings.mysql_user,
            "database": settings.mysql_database,
            "has_password": bool(settings.mysql_password),
        },
    }


@router.post("/api/settings/provider")
async def update_provider(req: ProviderUpdate):
    """Aggiorna un provider LLM."""
    if not _llm:
        raise HTTPException(503, "LLM Provider non inizializzato")
    _llm.update_provider(req.provider, req.api_key, req.model)
    return {"status": "updated", "provider": req.provider}


@router.post("/api/settings/update")
async def update_settings(req: SettingsUpdate):
    """Aggiorna le impostazioni generali."""
    if req.llm_mode:
        settings.llm_mode = req.llm_mode
    if req.active_provider:
        settings.active_provider = req.active_provider
    if req.board_chairman:
        settings.board_chairman = req.board_chairman
    if req.mysql_host:
        settings.mysql_host = req.mysql_host
    if req.mysql_port:
        settings.mysql_port = req.mysql_port
    if req.mysql_user:
        settings.mysql_user = req.mysql_user
    if req.mysql_password:
        settings.mysql_password = req.mysql_password
    if req.mysql_database:
        settings.mysql_database = req.mysql_database
    return {"status": "updated"}


@router.post("/api/settings/test-provider/{provider}")
async def test_provider(provider: str):
    """Testa la connessione a un provider LLM."""
    if not _llm:
        raise HTTPException(503, "LLM Provider non inizializzato")
    return await _llm.test_provider(provider)


@router.get("/api/settings/providers")
async def list_providers():
    """Lista i provider disponibili."""
    if not _llm:
        return {"providers": []}
    return {"providers": _llm.available_providers}
