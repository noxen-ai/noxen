# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Noxen. See LICENSE for details.
"""Tenant Auth — FastAPI dependency for tenant context extraction.

Phase 8 Step 8.3: Extracts tenant from request via:
1. Bearer API key (SaaS mode)
2. X-Tenant-ID header (on-premise)
3. Default tenant (multitenant=false)

If NOXEN_MULTITENANT_ENABLED=false (default):
  -> Always returns the "default" tenant
  -> No auth required
  -> Backward compatible with on-premise installs
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.tenants.model import Tenant, TenantStatus

security = HTTPBearer(auto_error=False)

# Module-level singleton (injected at startup)
_tenant_repo = None
_multitenant_enabled = False
_admin_api_key = ""


def init_auth(
    tenant_repository=None,
    multitenant_enabled: bool = False,
    admin_api_key: str = "",
) -> None:
    """Inject dependencies at startup."""
    global _tenant_repo, _multitenant_enabled, _admin_api_key
    _tenant_repo = tenant_repository
    _multitenant_enabled = multitenant_enabled
    _admin_api_key = admin_api_key


@dataclass
class TenantContext:
    """Tenant context attached to each request."""
    tenant: Tenant
    tenant_id: str
    is_admin: bool = False


async def get_tenant_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TenantContext:
    """FastAPI dependency to extract tenant from request.

    Strategies (in order):
    1. Header Authorization: Bearer {api_key}
    2. Header X-Tenant-ID (on-premise single-tenant)
    3. Default tenant (if multitenant=false)
    """
    if not _tenant_repo:
        raise HTTPException(503, "Tenant system not initialized")

    # On-premise mode: no auth required
    if not _multitenant_enabled:
        tenant = await _tenant_repo.ensure_default_tenant()
        return TenantContext(tenant=tenant, tenant_id=tenant.id, is_admin=True)

    # SaaS mode: check admin key first
    if credentials and _admin_api_key and credentials.credentials == _admin_api_key:
        tenant = await _tenant_repo.ensure_default_tenant()
        return TenantContext(tenant=tenant, tenant_id=tenant.id, is_admin=True)

    # SaaS mode: require API key
    if not credentials:
        # Check X-Tenant-ID header as fallback
        tenant_header = request.headers.get("X-Tenant-ID")
        if tenant_header:
            tenant = await _tenant_repo.get(tenant_header)
            if tenant:
                return TenantContext(tenant=tenant, tenant_id=tenant.id)

        raise HTTPException(401, "API key required")

    # Validate API key
    tenant = await _tenant_repo.get_by_api_key(credentials.credentials)
    if not tenant:
        raise HTTPException(401, "Invalid API key")

    if tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(403, f"Tenant {tenant.status.value}")

    return TenantContext(tenant=tenant, tenant_id=tenant.id)


async def require_admin(
    ctx: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    """Require admin access."""
    if not ctx.is_admin:
        raise HTTPException(403, "Admin required")
    return ctx
