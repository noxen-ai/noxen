"""API Routes: Public License endpoint.

Returns the current tenant's license info.
No admin required — uses tenant context from auth.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core.tenants.auth import TenantContext, get_tenant_context

router = APIRouter(prefix="/api/tenants", tags=["license"])

# Module-level singleton (injected at startup)
_tenant_repo = None


def init_router(tenant_repository=None, **kwargs) -> None:
    """Inject dependencies at startup."""
    global _tenant_repo
    _tenant_repo = tenant_repository


@router.get("/license")
async def get_my_license(
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Get license for the current tenant."""
    if not _tenant_repo:
        return {"error": "License system not initialized"}

    lic = await _tenant_repo.get_license(ctx.tenant_id)

    if not lic:
        from config.settings import settings
        if not settings.multitenant_enabled:
            from core.tenants.model import TenantLicense
            lic = TenantLicense.create_onpremise(ctx.tenant_id)
            await _tenant_repo.set_license(lic)
        else:
            return {"error": "No license found", "tenant_id": ctx.tenant_id}

    d = lic.to_dict()
    d["plan_display"] = lic.plan_name.title()
    d["is_active"] = lic.is_active
    d["days_remaining"] = lic.days_remaining
    d["projects_remaining"] = lic.projects_remaining
    return d
