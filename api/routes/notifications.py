"""Notification Engine API routes.

Phase 5: Webhook endpoints for notification management, approval actions,
and channel status. Integrates with NotificationEngine singleton.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.tenants.auth import TenantContext, get_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# ── Module-level state (injected via init_router) ────────────────────
_notification_engine = None


def init_router(notification_engine) -> None:
    """Inject NotificationEngine dependency."""
    global _notification_engine
    _notification_engine = notification_engine
    logger.info("Notification routes initialized")


# ── Request/Response models ──────────────────────────────────────────

class ApproveRequest(BaseModel):
    approval_id: str = Field(..., description="Approval ID to approve")


class RejectRequest(BaseModel):
    approval_id: str = Field(..., description="Approval ID to reject")


class TestNotificationRequest(BaseModel):
    title: str = Field(default="Noxen Test", description="Notification title")
    message: str = Field(default="This is a test notification", description="Notification body")
    level: str = Field(default="info", description="Level: info, warning, error, success")


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/status")
async def notification_status() -> dict[str, Any]:
    """Get notification engine status: channels, pending approvals."""
    if _notification_engine is None:
        return {"status": "not_initialized", "channels": [], "pending_approvals": 0}

    return _notification_engine.get_status()


@router.get("/channels")
async def list_channels() -> dict[str, Any]:
    """List all registered notification channels."""
    if _notification_engine is None:
        return {"channels": []}

    return {"channels": _notification_engine.get_channels()}


@router.get("/approvals")
async def list_approvals() -> dict[str, Any]:
    """List pending (unresolved) approvals."""
    if _notification_engine is None:
        return {"approvals": []}

    pending = _notification_engine.get_pending_approvals()
    return {
        "approvals": [
            {
                "approval_id": p.approval_id,
                "run_id": p.plan.run_id,
                "project_name": p.plan.project_name,
                "total_goals": p.plan.total_goals,
                "created_at": p.created_at.isoformat(),
                "reminder_count": p.reminder_count,
            }
            for p in pending
        ]
    }


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: str) -> dict[str, Any]:
    """Get details of a specific approval."""
    if _notification_engine is None:
        raise HTTPException(status_code=503, detail="Notification engine not initialized")

    approval = _notification_engine.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")

    return {
        "approval_id": approval.approval_id,
        "run_id": approval.plan.run_id,
        "project_name": approval.plan.project_name,
        "total_goals": approval.plan.total_goals,
        "created_at": approval.created_at.isoformat(),
        "reminder_count": approval.reminder_count,
        "resolved": approval.resolved,
        "resolution": approval.resolution,
        "results": [
            {
                "channel": r.channel,
                "success": r.success,
                "message_id": r.message_id,
                "error": r.error,
            }
            for r in approval.results
        ],
    }


@router.post("/approve")
async def approve_notification(
    req: ApproveRequest,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Approve a pending notification request."""
    if _notification_engine is None:
        raise HTTPException(status_code=503, detail="Notification engine not initialized")

    success = _notification_engine.resolve_approval(req.approval_id, "approved")
    if not success:
        return {"status": "not_found_or_resolved", "approval_id": req.approval_id}

    return {"status": "approved", "approval_id": req.approval_id}


@router.post("/reject")
async def reject_notification(
    req: RejectRequest,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Reject a pending notification request."""
    if _notification_engine is None:
        raise HTTPException(status_code=503, detail="Notification engine not initialized")

    success = _notification_engine.resolve_approval(req.approval_id, "rejected")
    if not success:
        return {"status": "not_found_or_resolved", "approval_id": req.approval_id}

    return {"status": "rejected", "approval_id": req.approval_id}


@router.post("/reminder/{approval_id}")
async def send_reminder(approval_id: str) -> dict[str, Any]:
    """Manually send a reminder for a pending approval."""
    if _notification_engine is None:
        raise HTTPException(status_code=503, detail="Notification engine not initialized")

    results = await _notification_engine.send_reminder(approval_id)
    return {
        "status": "sent",
        "results": [
            {"channel": r.channel, "success": r.success, "error": r.error}
            for r in results
        ],
    }


@router.post("/test")
async def test_notification(
    req: TestNotificationRequest,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Send a test notification to all configured channels."""
    if _notification_engine is None:
        raise HTTPException(status_code=503, detail="Notification engine not initialized")

    results = await _notification_engine.send_notification(
        title=req.title,
        message=req.message,
        level=req.level,
    )
    return {
        "status": "sent",
        "results": [
            {"channel": r.channel, "success": r.success, "error": r.error}
            for r in results
        ],
    }
