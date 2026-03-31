"""API Routes: Bridge per Claude / VS Code / Tool esterni.

Questo endpoint espone Noxen come "Tool" richiamabile da:
  - Claude Code (custom tool / MCP server)
  - VS Code extensions
  - Qualsiasi client HTTP

Implementa il protocollo OpenAI-compatible per function calling,
cosi' che qualsiasi LLM possa usare Noxen come tool provider.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.project_manager import ProjectManager
from core.skill_manager import SkillManager

logger = logging.getLogger("noxen.bridge")

router = APIRouter(prefix="/api/bridge", tags=["bridge"])

_skill_manager: SkillManager | None = None
_project_manager: ProjectManager | None = None


def init_router(sm: SkillManager, pm: ProjectManager) -> None:
    global _skill_manager, _project_manager
    _skill_manager = sm
    _project_manager = pm


# ── Modelli Request/Response ──────────────────────────────────────────

class ToolCallRequest(BaseModel):
    """Formato compatibile con OpenAI function calling."""
    tool: str
    arguments: dict[str, Any] = {}


class BatchToolCallRequest(BaseModel):
    """Esecuzione multipla di tool in sequenza."""
    calls: list[ToolCallRequest]


class QueryRequest(BaseModel):
    """Query al codebase con contesto."""
    query: str
    project: str | None = None
    n_results: int = 5
    include_skills: bool = True


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/manifest")
async def get_manifest():
    """Manifesto del Hub — usato da Claude/VS Code per scoprire le capabilities.

    Questo endpoint ritorna tutte le informazioni necessarie per registrare
    Noxen come tool provider esterno.
    """
    if not _skill_manager or not _project_manager:
        raise HTTPException(503, "Hub non pronto")

    tools = _skill_manager.get_tool_schemas()

    # Aggiungi tool built-in del Hub
    builtin_tools = [
        {
            "type": "function",
            "function": {
                "name": "hub_search_code",
                "description": "Cerca nel codice indicizzato di un progetto registrato su Noxen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "La query di ricerca"},
                        "project": {"type": "string", "description": "Nome del progetto"},
                        "n_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query", "project"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "hub_list_projects",
                "description": "Elenca tutti i progetti registrati su Noxen con il loro stato di indicizzazione.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "hub_index_project",
                "description": "Avvia l'indicizzazione di un progetto in background.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Nome del progetto"},
                    },
                    "required": ["project"],
                },
            },
        },
    ]

    return {
        "name": "Noxen",
        "version": "0.1.0",
        "description": "Local AI Orchestrator per Multi-Repo Development",
        "tools": tools + builtin_tools,
        "projects": list(_project_manager.projects.keys()),
        "skills_count": _skill_manager.active_count,
    }


@router.post("/call")
async def call_tool(req: ToolCallRequest):
    """Esegui un singolo tool. Endpoint principale per Claude/VS Code."""
    if not _skill_manager or not _project_manager:
        raise HTTPException(503, "Hub non pronto")

    start = time.time()

    # Controlla se è un tool built-in
    if req.tool == "hub_search_code":
        result = await _handle_search(req.arguments)
    elif req.tool == "hub_list_projects":
        result = {"projects": _project_manager.to_dict()}
    elif req.tool == "hub_index_project":
        result = await _handle_index(req.arguments)
    else:
        # Delega al SkillManager
        skill_result = await _skill_manager.execute_skill(
            skill_name=req.tool, **req.arguments
        )
        if not skill_result.success:
            raise HTTPException(400, detail=skill_result.error)
        result = {"data": skill_result.data, "metadata": skill_result.metadata}

    elapsed = round(time.time() - start, 3)
    return {
        "tool": req.tool,
        "result": result,
        "elapsed_seconds": elapsed,
    }


@router.post("/batch")
async def batch_call(req: BatchToolCallRequest):
    """Esegui piu' tool in sequenza."""
    results = []
    for call in req.calls:
        try:
            single = ToolCallRequest(tool=call.tool, arguments=call.arguments)
            res = await call_tool(single)
            results.append(res)
        except HTTPException as e:
            results.append({"tool": call.tool, "error": e.detail})
    return {"results": results}


@router.post("/query")
async def smart_query(req: QueryRequest):
    """Query intelligente: cerca nel codice e suggerisce skill rilevanti.

    Usato da Claude per ottenere contesto prima di rispondere.
    """
    if not _project_manager:
        raise HTTPException(503, "Hub non pronto")

    response: dict[str, Any] = {"query": req.query}

    # Cerca nel codice se specificato un progetto (via Qdrant)
    if req.project:
        try:
            from core.ingestor import Ingestor
            # Usa search semplificata dal ProjectManager (che cerca in "codebase")
            results = _project_manager.search(req.project, req.query, n_results=req.n_results)
            if results:
                response["code_context"] = [
                    {
                        "content": r.get("document", "")[:800],
                        "file_path": r.get("metadata", {}).get("file_path", ""),
                        "lines": f"{r.get('metadata', {}).get('start_line', '?')}-{r.get('metadata', {}).get('end_line', '?')}",
                        "language": r.get("metadata", {}).get("language", ""),
                    }
                    for r in results
                ]
        except Exception as e:
            response["code_context_error"] = str(e)
    else:
        # Cerca in tutti i progetti
        response["available_projects"] = list(_project_manager.projects.keys())

    # Suggerisci skill rilevanti
    if req.include_skills and _skill_manager:
        response["available_skills"] = [
            {"name": s.metadata.name, "description": s.metadata.description}
            for s in _skill_manager.skills.values()
        ]

    return response


# ── Handler interni ───────────────────────────────────────────────────

async def _handle_search(args: dict) -> dict:
    query = args.get("query", "")
    project = args.get("project", "")
    n = args.get("n_results", 5)

    if not project or not _project_manager:
        return {"error": "Progetto non specificato"}

    if not _project_manager.get(project):
        return {"error": f"Progetto '{project}' non trovato"}

    results = _project_manager.search(project, query, n_results=n)

    return {
        "matches": [
            {
                "content": r.get("document", "")[:500],
                "file": r.get("metadata", {}).get("file_path", ""),
                "lines": f"{r.get('metadata', {}).get('start_line', '?')}-{r.get('metadata', {}).get('end_line', '?')}",
            }
            for r in results
        ]
    }


async def _handle_index(args: dict) -> dict:
    from core.ingestor import Ingestor
    # L'ingestor viene passato tramite il project manager route
    project = args.get("project", "")
    return {"status": "use_dedicated_endpoint", "hint": f"POST /api/projects/{project}/index"}
