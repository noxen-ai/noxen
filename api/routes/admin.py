"""API Routes: Tenant Admin — Step 8.6.

Admin-only CRUD for tenant management, API keys, and usage stats.
All endpoints require admin privileges (on-premise: always admin,
SaaS: requires admin API key).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.tenants.auth import TenantContext, require_admin

router = APIRouter(prefix="/api/admin/tenants", tags=["admin"])

# ── Module-level singletons (injected at startup) ────────────────────
_tenant_repo = None
_qdrant_client = None


def init_router(tenant_repository=None, qdrant_client=None) -> None:
    """Inject dependencies at startup."""
    global _tenant_repo, _qdrant_client
    _tenant_repo = tenant_repository
    _qdrant_client = qdrant_client


def _get_repo():
    if not _tenant_repo:
        raise HTTPException(503, "TenantRepository not initialized")
    return _tenant_repo


def _get_qdrant():
    if not _qdrant_client:
        raise HTTPException(503, "QdrantClient not initialized")
    return _qdrant_client


# ── Request/Response Models ──────────────────────────────────────────

class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: str = Field(..., min_length=2, max_length=50, pattern="^[a-z0-9-]+$")
    plan: str = Field(default="free", pattern="^(free|pro|enterprise)$")


class UpdateTenantRequest(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = Field(None, pattern="^(free|pro|enterprise)$")
    status: Optional[str] = Field(None, pattern="^(active|suspended|trial)$")


class UpgradeLicenseRequest(BaseModel):
    plan: str = Field(...)
    purchase_reference: str = Field(...)
    notes: str = Field(default="")


class ExtendLicenseRequest(BaseModel):
    days: int = Field(..., gt=0)
    reason: str = Field(default="")


class CreateApiKeyRequest(BaseModel):
    key_name: str = Field(..., min_length=2, max_length=100)


# ── Tenant CRUD ──────────────────────────────────────────────────────

@router.post("/")
async def create_tenant(
    req: CreateTenantRequest,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Create a new tenant."""
    repo = _get_repo()

    # Check slug uniqueness
    existing = await repo.get_by_slug(req.slug)
    if existing:
        raise HTTPException(409, f"Tenant with slug '{req.slug}' already exists")

    from core.tenants.model import TenantLimitError, TenantPlan, LicenseError

    try:
        tenant = await repo.create(
            name=req.name,
            slug=req.slug,
            plan=TenantPlan(req.plan),
        )
    except TenantLimitError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except LicenseError as e:
        raise HTTPException(status_code=402, detail=str(e))
    return {"status": "created", "tenant": tenant.to_dict()}


@router.get("/")
async def list_tenants(
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """List all tenants."""
    repo = _get_repo()
    tenants = await repo.list_all()
    return {
        "tenants": [t.to_dict() for t in tenants],
        "count": len(tenants),
    }


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Get a specific tenant."""
    repo = _get_repo()
    tenant = await repo.get(tenant_id)
    if not tenant:
        raise HTTPException(404, f"Tenant {tenant_id} not found")
    return {"tenant": tenant.to_dict()}


@router.patch("/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    req: UpdateTenantRequest,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Update a tenant (name, plan, status)."""
    repo = _get_repo()
    tenant = await repo.get(tenant_id)
    if not tenant:
        raise HTTPException(404, f"Tenant {tenant_id} not found")

    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.plan is not None:
        from core.tenants.model import TenantPlan
        updates["plan"] = TenantPlan(req.plan)
    if req.status is not None:
        from core.tenants.model import TenantStatus
        updates["status"] = TenantStatus(req.status)

    if not updates:
        return {"status": "no_changes", "tenant": tenant.to_dict()}

    updated = await repo.update(tenant_id, **updates)
    if not updated:
        raise HTTPException(500, "Failed to update tenant")

    return {"status": "updated", "tenant": updated.to_dict()}


@router.delete("/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    delete_data: bool = Query(False, description="Also delete tenant data from Qdrant"),
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Delete a tenant. Optionally delete all tenant data from Qdrant."""
    repo = _get_repo()

    from core.tenants.repository import TenantRepository
    if tenant_id == TenantRepository.DEFAULT_TENANT_ID:
        raise HTTPException(400, "Cannot delete the default tenant")

    tenant = await repo.get(tenant_id)
    if not tenant:
        raise HTTPException(404, f"Tenant {tenant_id} not found")

    result: dict[str, Any] = {"status": "deleted", "tenant_id": tenant_id}

    # Optionally delete Qdrant data
    if delete_data:
        try:
            qdrant = _get_qdrant()
            deleted_counts = await qdrant.delete_tenant_data(tenant_id)
            result["qdrant_deleted"] = deleted_counts
        except Exception as e:
            result["qdrant_delete_error"] = str(e)

    deleted = await repo.delete(tenant_id)
    if not deleted:
        raise HTTPException(500, "Failed to delete tenant")

    return result


# ── License Management ───────────────────────────────────────────────


@router.get("/{tenant_id}/license")
async def get_license(
    tenant_id: str,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Get license for a tenant."""
    repo = _get_repo()
    lic = await repo.get_license(tenant_id)
    if not lic:
        raise HTTPException(404, f"No license found for tenant {tenant_id}")
    return lic.to_dict()


@router.post("/{tenant_id}/license/upgrade")
async def upgrade_license(
    tenant_id: str,
    req: UpgradeLicenseRequest,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Upgrade a tenant's license."""
    from core.tenants.model import NOXEN_PLANS

    repo = _get_repo()
    tenant = await repo.get(tenant_id)
    if not tenant:
        raise HTTPException(404, f"Tenant {tenant_id} not found")
    if req.plan not in NOXEN_PLANS:
        raise HTTPException(400, f"Invalid plan: {req.plan}. Valid: {list(NOXEN_PLANS.keys())}")

    new_lic = await repo.upgrade_license(
        tenant_id=tenant_id,
        plan_name=req.plan,
        purchase_reference=req.purchase_reference,
        notes=req.notes,
    )
    return new_lic.to_dict()


@router.post("/{tenant_id}/license/extend")
async def extend_license(
    tenant_id: str,
    req: ExtendLicenseRequest,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Extend a tenant's license expiry date."""
    from datetime import timedelta

    repo = _get_repo()
    lic = await repo.get_license(tenant_id)
    if not lic:
        raise HTTPException(404, f"No license found for tenant {tenant_id}")

    if lic.expires_at is None:
        # Enterprise/on-premise: no expiry to extend
        return lic.to_dict()

    lic.expires_at = lic.expires_at + timedelta(days=req.days)
    if req.reason:
        lic.notes = f"{lic.notes}\nExtended +{req.days}d: {req.reason}".strip()
    await repo.set_license(lic)
    return lic.to_dict()


# ── License List (admin-level) ──────────────────────────────────────

license_router = APIRouter(prefix="/api/admin/licenses", tags=["admin"])


@license_router.get("/")
async def list_licenses(
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """List all licenses with tenant info."""
    repo = _get_repo()
    tenants = await repo.list_all()
    result = []
    for t in tenants:
        lic = await repo.get_license(t.id)
        if lic:
            result.append({
                "tenant_id": t.id,
                "name": t.name,
                "plan": lic.plan_name,
                "is_active": lic.is_active,
                "days_remaining": lic.days_remaining,
                "projects_activated": lic.projects_activated,
            })
    return {"licenses": result, "count": len(result)}


@license_router.get("/expiring")
async def list_expiring_licenses(
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """List licenses expiring within 30 days."""
    repo = _get_repo()
    tenants = await repo.list_all()
    result = []
    for t in tenants:
        lic = await repo.get_license(t.id)
        if lic and lic.is_active and lic.days_remaining is not None and lic.days_remaining <= 30:
            result.append({
                "tenant_id": t.id,
                "name": t.name,
                "plan": lic.plan_name,
                "is_active": lic.is_active,
                "days_remaining": lic.days_remaining,
                "projects_activated": lic.projects_activated,
            })
    return {"licenses": result, "count": len(result)}


# ── API Key Management ───────────────────────────────────────────────

@router.post("/{tenant_id}/api-keys")
async def create_api_key(
    tenant_id: str,
    req: CreateApiKeyRequest,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Create an API key for a tenant. Returns plaintext key (shown ONCE)."""
    repo = _get_repo()
    tenant = await repo.get(tenant_id)
    if not tenant:
        raise HTTPException(404, f"Tenant {tenant_id} not found")

    plaintext_key = await repo.create_api_key(tenant_id, req.key_name)
    return {
        "status": "created",
        "tenant_id": tenant_id,
        "key_name": req.key_name,
        "api_key": plaintext_key,
        "warning": "Store this key securely. It cannot be retrieved again.",
    }


@router.delete("/{tenant_id}/api-keys/{key_hash}")
async def revoke_api_key(
    tenant_id: str,
    key_hash: str,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Revoke an API key."""
    repo = _get_repo()
    revoked = await repo.revoke_api_key(key_hash)
    if not revoked:
        raise HTTPException(404, "API key not found")
    return {"status": "revoked", "key_hash": key_hash}


# ── Usage Stats ──────────────────────────────────────────────────────

@router.get("/{tenant_id}/usage")
async def get_tenant_usage(
    tenant_id: str,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Get usage stats for a tenant."""
    repo = _get_repo()
    tenant = await repo.get(tenant_id)
    if not tenant:
        raise HTTPException(404, f"Tenant {tenant_id} not found")

    from core.tenants.model import PLAN_LIMITS

    limits = PLAN_LIMITS[tenant.plan]
    return {
        "tenant_id": tenant_id,
        "plan": tenant.plan.value,
        "sessions_this_month": tenant.sessions_this_month,
        "limits": {
            "max_projects": limits.max_projects,
            "max_sessions_per_month": limits.max_sessions_per_month,
            "max_sandbox_size_gb": limits.max_sandbox_size_gb,
            "board_providers": limits.board_providers,
            "notifications_enabled": limits.notifications_enabled,
        },
        "usage_pct": round(
            (tenant.sessions_this_month / limits.max_sessions_per_month) * 100, 1
        ) if limits.max_sessions_per_month > 0 else 0,
    }


@router.post("/{tenant_id}/reset-sessions")
async def reset_sessions(
    tenant_id: str,
    ctx: TenantContext = Depends(require_admin),
) -> dict[str, Any]:
    """Reset monthly session counter for a tenant."""
    repo = _get_repo()
    await repo.reset_monthly_sessions(tenant_id)
    return {"status": "reset", "tenant_id": tenant_id}
