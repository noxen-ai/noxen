"""API Routes: Chat (DEPRECATO — usa /api/orchestrator/chat).

Questo modulo esiste solo per backward compatibility.
Tutte le nuove integrazioni devono usare /api/orchestrator/chat.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from config import settings

logger = logging.getLogger("noxen.chat")

router = APIRouter(prefix="/api/chat", tags=["chat (deprecated)"])


def init_router(pm: Any) -> None:
    """Noop — mantenuto per backward compat con main.py."""
    pass


class ChatRequest(BaseModel):
    message: str
    project: str | None = None
    model: str | None = None
    n_context: int = 5
    stream: bool = False
    history: list[dict[str, str]] = []


@router.post("/")
async def chat(req: ChatRequest):
    """DEPRECATO: usa POST /api/orchestrator/chat.

    Questo endpoint redirige all'orchestratore unificato.
    """
    return {
        "deprecated": True,
        "redirect": "/api/orchestrator/chat",
        "message": "Usa POST /api/orchestrator/chat per la chat unificata con Knowledge Base + RAG + DB",
    }


@router.get("/models")
async def list_models():
    """Elenca i modelli disponibili su Ollama."""
    try:
        import ollama as ollama_client
        models = ollama_client.list()
        return {
            "models": [
                {
                    "name": m.get("name", m.get("model", "unknown")),
                    "size_gb": round(m.get("size", 0) / 1e9, 1),
                }
                for m in models.get("models", [])
            ]
        }
    except Exception as e:
        return {"models": [], "error": str(e), "hint": "Assicurati che Ollama sia in esecuzione"}
