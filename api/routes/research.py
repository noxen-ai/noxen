"""API Routes: Research Agent.

Endpoint per il Research Agent:
  - POST /api/research          — lancio pipeline completo
  - GET  /api/research/search   — ricerca rapida GitHub
  - POST /api/research/gap      — detect knowledge gap
  - GET  /api/research/status   — stato componenti
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from core.tenants.auth import TenantContext, get_tenant_context

router = APIRouter(prefix="/api/research", tags=["research"])

# Dependency injection
_research_agent = None


def init_router(research_agent=None):
    """Inietta le dipendenze nel router."""
    global _research_agent
    _research_agent = research_agent


# ── Request/Response Models ──────────────────────────────────────────

class ResearchRequestModel(BaseModel):
    """Richiesta di ricerca."""
    query: str = Field(..., min_length=2, max_length=500)
    context: str = ""
    language: Optional[str] = None
    max_repos: int = Field(default=5, ge=1, le=20)
    max_web_results: int = Field(default=10, ge=1, le=50)
    auto_save: bool = True


class GapDetectModel(BaseModel):
    """Richiesta di gap detection."""
    query: str = Field(..., min_length=2, max_length=500)
    existing_skills: list[str] = Field(default_factory=list)


class QuickSearchModel(BaseModel):
    """Parametri per ricerca rapida."""
    query: str = Field(..., min_length=2, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


# ── Endpoints ───────────────────────────────────────────────────────

@router.post("")
async def run_research(
    request: ResearchRequestModel,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Lancia il pipeline di ricerca completo.

    Cerca su GitHub, analizza repo, ricerca web, genera skill.
    """
    if not _research_agent:
        raise HTTPException(status_code=503, detail="Research Agent not configured")

    from core.research_agent import ResearchRequest

    req = ResearchRequest(
        query=request.query,
        context=request.context,
        language=request.language,
        max_repos=request.max_repos,
        max_web_results=request.max_web_results,
        auto_save=request.auto_save,
    )

    result = await _research_agent.research(req)

    return {
        "query": result.query,
        "repos_found": len(result.repos_found),
        "repos_analyzed": len(result.repos_analyzed),
        "web_results": sum(wr.total_results for wr in result.web_results),
        "skills_generated": len(result.skills_generated),
        "skills_saved": result.skills_saved,
        "duration_s": round(result.duration_s, 2),
        "errors": result.errors,
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "tags": s.tags,
                "confidence": s.confidence,
            }
            for s in result.skills_generated
        ],
        "repos": [
            {
                "full_name": r.full_name,
                "url": r.url,
                "stars": r.stars,
                "language": r.language,
                "relevance_score": round(r.relevance_score, 3),
            }
            for r in result.repos_found
        ],
    }


@router.get("/search")
async def quick_search(
    query: str,
    limit: int = 5,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Ricerca rapida su GitHub senza analisi completa."""
    if not _research_agent:
        raise HTTPException(status_code=503, detail="Research Agent not configured")

    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Query too short")

    candidates = await _research_agent.quick_search(query, limit=min(limit, 20))

    return {
        "query": query,
        "results": [
            {
                "full_name": c.full_name,
                "url": c.url,
                "description": c.description,
                "stars": c.stars,
                "language": c.language,
                "topics": c.topics,
                "relevance_score": round(c.relevance_score, 3),
            }
            for c in candidates
        ],
    }


@router.post("/gap")
async def detect_gap(
    request: GapDetectModel,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Detecta se c'e' una lacuna nella knowledge base."""
    if not _research_agent:
        raise HTTPException(status_code=503, detail="Research Agent not configured")

    has_gap = await _research_agent.detect_knowledge_gap(
        request.query,
        existing_skills=request.existing_skills,
    )

    return {
        "query": request.query,
        "has_gap": has_gap,
        "existing_skills_checked": len(request.existing_skills),
    }


@router.get("/status")
async def research_status():
    """Stato dei componenti del Research Agent."""
    if not _research_agent:
        return {
            "configured": False,
            "components": {},
        }

    return {
        "configured": True,
        "components": {
            "github_client": _research_agent._github is not None,
            "repo_analyzer": _research_agent._analyzer is not None,
            "web_researcher": _research_agent._web is not None,
            "skill_builder": _research_agent._skill_builder is not None,
            "knowledge_base": _research_agent._kb is not None,
        },
    }
