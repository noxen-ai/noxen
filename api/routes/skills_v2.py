"""API Routes: Skill System v2 — Knowledge Skills lifecycle.

Phase 6 Step 6.7: REST endpoints for the knowledge skill system.
Manages skill pool, board review, usage tracking, and analytics.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.skills.lifecycle import SkillStatus
from core.tenants.auth import TenantContext, get_tenant_context

router = APIRouter(prefix="/api/skills/v2", tags=["skills-v2"])

# ── Module-level singletons (injected at startup) ────────────────────
_repo = None
_board = None
_updater = None
_tracker = None


def init_router(
    skill_repository=None,
    board_reviewer=None,
    skill_updater=None,
    usage_tracker=None,
) -> None:
    """Inject dependencies at startup."""
    global _repo, _board, _updater, _tracker
    _repo = skill_repository
    _board = board_reviewer
    _updater = skill_updater
    _tracker = usage_tracker


def _get_repo():
    if not _repo:
        raise HTTPException(503, "SkillRepository not initialized")
    return _repo


def _get_board():
    if not _board:
        raise HTTPException(503, "SkillBoardReviewer not initialized")
    return _board


def _get_updater():
    if not _updater:
        raise HTTPException(503, "SkillUpdater not initialized")
    return _updater


def _get_tracker():
    if not _tracker:
        raise HTTPException(503, "SkillUsageTracker not initialized")
    return _tracker


# ── Request/Response Models ──────────────────────────────────────────

class SkillApproveRequest(BaseModel):
    board_feedback: str = ""


class SkillRejectRequest(BaseModel):
    reason: str = "Board rejected"


class SkillImproveRequest(BaseModel):
    feedback: str
    iteration: int = 1


class RecordUsageRequest(BaseModel):
    session_id: str
    project_name: str
    task_type: str
    outcome: str = Field(..., pattern="^(success|partial|failure)$")
    feedback: str = ""


class SkillSearchRequest(BaseModel):
    query: str
    min_confidence: float = 0.0
    limit: int = 5


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/pool")
async def get_skill_pool(
    status: Optional[str] = Query(None, description="Filter by status"),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Get the skill pool, optionally filtered by status."""
    repo = _get_repo()
    tenant_id = ctx.tenant_id

    if status:
        try:
            skill_status = SkillStatus(status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
        skills = await repo.list_by_status(skill_status, tenant_id=tenant_id)
    else:
        # Return stats instead of all skills
        stats = await repo.get_pool_stats(tenant_id=tenant_id)
        return {"pool": stats}

    return {
        "skills": [
            {
                "id": s.id,
                "name": s.name,
                "technology": s.technology,
                "version": s.version,
                "status": s.status.value,
                "confidence_score": s.metrics.confidence_score,
                "total_uses": s.metrics.total_uses,
            }
            for s in skills
        ],
        "count": len(skills),
    }


@router.get("/pool/{skill_id}")
async def get_skill(skill_id: str) -> dict[str, Any]:
    """Get a specific skill by ID."""
    repo = _get_repo()
    skill = await repo.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")

    return {
        "id": skill.id,
        "name": skill.name,
        "technology": skill.technology,
        "version": skill.version,
        "status": skill.status.value,
        "source": skill.source.value,
        "skill_md": skill.skill_md,
        "metrics": {
            "total_uses": skill.metrics.total_uses,
            "successful_uses": skill.metrics.successful_uses,
            "partial_uses": skill.metrics.partial_uses,
            "failed_uses": skill.metrics.failed_uses,
            "confidence_score": skill.metrics.confidence_score,
            "success_rate": skill.metrics.success_rate,
            "last_used": skill.metrics.last_used.isoformat() if skill.metrics.last_used else None,
        },
        "board_feedback": skill.board_feedback,
        "created_at": skill.created_at.isoformat(),
        "updated_at": skill.updated_at.isoformat(),
        "approved_at": skill.approved_at.isoformat() if skill.approved_at else None,
        "tenant_id": skill.tenant_id,
    }


@router.post("/pool/{skill_id}/approve")
async def approve_skill(skill_id: str, req: SkillApproveRequest) -> dict[str, str]:
    """Manually approve a skill."""
    repo = _get_repo()
    skill = await repo.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")

    await repo.approve(skill_id, board_feedback=req.board_feedback or "Manual approval")
    return {"status": "approved", "skill_id": skill_id}


@router.post("/pool/{skill_id}/reject")
async def reject_skill(skill_id: str, req: SkillRejectRequest) -> dict[str, str]:
    """Manually reject a skill."""
    repo = _get_repo()
    skill = await repo.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")

    await repo.reject(skill_id, reason=req.reason)
    return {"status": "rejected", "skill_id": skill_id}


@router.post("/pool/{skill_id}/improve")
async def improve_skill(skill_id: str, req: SkillImproveRequest) -> dict[str, str]:
    """Trigger skill improvement cycle."""
    updater = _get_updater()
    await updater.improve_skill(
        skill_id=skill_id,
        feedback=req.feedback,
        iteration=req.iteration,
    )
    return {"status": "improvement_started", "skill_id": skill_id}


@router.post("/pool/{skill_id}/usage")
async def record_usage(skill_id: str, req: RecordUsageRequest) -> dict[str, Any]:
    """Record a skill usage event."""
    tracker = _get_tracker()
    event = await tracker.record_usage(
        skill_id=skill_id,
        session_id=req.session_id,
        project_name=req.project_name,
        task_type=req.task_type,
        outcome=req.outcome,
        feedback=req.feedback,
    )
    if not event:
        raise HTTPException(404, f"Skill {skill_id} not found")

    return {
        "status": "recorded",
        "skill_id": skill_id,
        "outcome": event.outcome,
        "timestamp": event.timestamp.isoformat(),
    }


@router.get("/stats")
async def get_stats(
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Get skill pool statistics."""
    repo = _get_repo()
    stats = await repo.get_pool_stats(tenant_id=ctx.tenant_id)
    return {"stats": stats}


@router.get("/stats/{skill_id}")
async def get_skill_stats(skill_id: str) -> dict[str, Any]:
    """Get usage statistics for a specific skill."""
    tracker = _get_tracker()
    summary = await tracker.get_skill_usage_summary(skill_id)
    if "error" in summary:
        raise HTTPException(404, summary["error"])
    return {"usage": summary}


@router.post("/check-degraded")
async def check_degraded(
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Find skills with degraded confidence scores."""
    updater = _get_updater()
    degraded_ids = await updater.check_degraded_skills(tenant_id=ctx.tenant_id)
    return {
        "degraded_skills": degraded_ids,
        "count": len(degraded_ids),
        "threshold": updater.MIN_CONFIDENCE_THRESHOLD,
    }


@router.post("/search")
async def search_skills(
    req: SkillSearchRequest,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Semantic search for skills."""
    repo = _get_repo()
    skills = await repo.search(
        query=req.query,
        tenant_id=ctx.tenant_id,
        min_confidence=req.min_confidence,
        limit=req.limit,
    )
    return {
        "results": [
            {
                "id": s.id,
                "name": s.name,
                "technology": s.technology,
                "version": s.version,
                "confidence_score": s.metrics.confidence_score,
                "status": s.status.value,
            }
            for s in skills
        ],
        "count": len(skills),
    }


@router.get("/analytics")
async def get_analytics(
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Get usage analytics across all skills."""
    tracker = _get_tracker()
    analytics = await tracker.get_usage_analytics(tenant_id=ctx.tenant_id)
    return {"analytics": analytics}


@router.get("/history/{skill_id}")
async def get_skill_history(skill_id: str) -> dict[str, Any]:
    """Get skill history (board feedback, version, timestamps)."""
    repo = _get_repo()
    skill = await repo.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")

    return {
        "skill_id": skill.id,
        "name": skill.name,
        "version": skill.version,
        "status": skill.status.value,
        "board_feedback": skill.board_feedback,
        "board_votes": skill.board_votes,
        "created_at": skill.created_at.isoformat(),
        "updated_at": skill.updated_at.isoformat(),
        "approved_at": skill.approved_at.isoformat() if skill.approved_at else None,
        "metrics": {
            "total_uses": skill.metrics.total_uses,
            "confidence_score": skill.metrics.confidence_score,
        },
    }
