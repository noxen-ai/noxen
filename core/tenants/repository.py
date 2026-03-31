"""Tenant Repository — CRUD for tenants in SQLite.

Phase 8 Step 8.2: Manages tenant persistence in SQLite with
API key management, session counting, and default tenant support.

SQLite chosen over Qdrant because:
- Structured data with exact queries (no semantic search needed)
- ACID transactions for billing/limits
- Lightweight, embedded, zero external server
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.tenants.model import (
    NOXEN_PLANS,
    Tenant,
    TenantConfig,
    TenantLicense,
    TenantPlan,
    TenantStatus,
)

logger = logging.getLogger(__name__)


class TenantRepository:
    """CRUD for tenants persisted in SQLite."""

    DEFAULT_TENANT_ID = "default"

    def __init__(self, db_path: str = "./data/tenants.db") -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    sessions_this_month INTEGER DEFAULT 0,
                    total_sessions INTEGER DEFAULT 0,
                    total_skills_created INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_hash TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used TEXT,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS licenses (
                    tenant_id TEXT PRIMARY KEY,
                    plan_name TEXT NOT NULL,
                    projects_total INTEGER,
                    projects_activated INTEGER DEFAULT 0,
                    research_sessions_total INTEGER,
                    research_sessions_used INTEGER DEFAULT 0,
                    activated_at TEXT NOT NULL,
                    expires_at TEXT,
                    execution_sessions_count INTEGER DEFAULT 0,
                    purchase_reference TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activated_projects (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    project_path TEXT DEFAULT '',
                    activated_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                )
            """)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── CRUD ──────────────────────────────────────────────────────────

    async def create(self, tenant: Tenant) -> Tenant:
        """Create a new tenant. Returns the created tenant."""
        from core.tenants.model import TenantLimitError
        from config.settings import settings

        if not settings.multitenant_enabled:
            existing = await self.list_all()
            non_default = [t for t in existing if t.id != self.DEFAULT_TENANT_ID]
            if non_default:
                raise TenantLimitError(
                    "Il piano on-premise supporta un solo tenant. "
                    "Per gestire più tenant: noxen.ai/cloud"
                )

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO tenants
                   (id, slug, name, plan, status, config_json,
                    sessions_this_month, total_sessions, total_skills_created,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tenant.id,
                    tenant.slug,
                    tenant.name,
                    tenant.plan.value,
                    tenant.status.value,
                    json.dumps(tenant.config.to_dict()),
                    tenant.sessions_this_month,
                    tenant.total_sessions,
                    tenant.total_skills_created,
                    tenant.created_at.isoformat(),
                    tenant.updated_at.isoformat(),
                ),
            )
        return tenant

    async def get(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_tenant(row)

    async def get_by_slug(self, slug: str) -> Optional[Tenant]:
        """Get tenant by URL-safe slug."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tenants WHERE slug = ?", (slug,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_tenant(row)

    async def get_by_api_key(self, api_key: str) -> Optional[Tenant]:
        """Verify API key and return the tenant.

        Uses SHA-256 hash of the key, not plaintext.
        """
        key_hash = self._hash_key(api_key)
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT t.* FROM tenants t
                   JOIN api_keys ak ON t.id = ak.tenant_id
                   WHERE ak.key_hash = ? AND ak.is_active = 1""",
                (key_hash,),
            ).fetchone()

            if row:
                # Update last_used
                conn.execute(
                    "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
                    (datetime.now().isoformat(), key_hash),
                )

        if not row:
            return None
        return self._row_to_tenant(row)

    async def update(self, tenant: Tenant) -> None:
        """Update an existing tenant."""
        tenant.updated_at = datetime.now()
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE tenants SET
                   name = ?, slug = ?, plan = ?, status = ?,
                   config_json = ?, sessions_this_month = ?,
                   total_sessions = ?, total_skills_created = ?,
                   updated_at = ?
                   WHERE id = ?""",
                (
                    tenant.name,
                    tenant.slug,
                    tenant.plan.value,
                    tenant.status.value,
                    json.dumps(tenant.config.to_dict()),
                    tenant.sessions_this_month,
                    tenant.total_sessions,
                    tenant.total_skills_created,
                    tenant.updated_at.isoformat(),
                    tenant.id,
                ),
            )

    async def delete(self, tenant_id: str) -> bool:
        """Delete tenant and its API keys. Returns True if deleted."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM api_keys WHERE tenant_id = ?", (tenant_id,))
            cursor = conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        return cursor.rowcount > 0

    async def list_all(self) -> List[Tenant]:
        """List all tenants."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM tenants ORDER BY created_at").fetchall()
        return [self._row_to_tenant(row) for row in rows]

    # ── API Keys ──────────────────────────────────────────────────────

    async def create_api_key(self, tenant_id: str, key_name: str) -> str:
        """Generate and store a new API key.

        Returns the plaintext key (shown only once).
        Only the SHA-256 hash is stored.
        """
        raw_key = f"nh_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_key(raw_key)

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO api_keys (key_hash, tenant_id, name, created_at, is_active)
                   VALUES (?, ?, ?, ?, 1)""",
                (key_hash, tenant_id, key_name, datetime.now().isoformat()),
            )

        return raw_key

    async def revoke_api_key(self, key_hash: str) -> bool:
        """Revoke an API key by its hash."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET is_active = 0 WHERE key_hash = ?",
                (key_hash,),
            )
        return cursor.rowcount > 0

    async def list_api_keys(self, tenant_id: str) -> list[dict]:
        """List API keys for a tenant (hashes only, not plaintext)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT key_hash, name, created_at, last_used, is_active
                   FROM api_keys WHERE tenant_id = ? ORDER BY created_at""",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Session Tracking ──────────────────────────────────────────────

    async def increment_sessions(self, tenant_id: str) -> None:
        """Increment session counters."""
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE tenants SET
                   sessions_this_month = sessions_this_month + 1,
                   total_sessions = total_sessions + 1,
                   updated_at = ?
                   WHERE id = ?""",
                (datetime.now().isoformat(), tenant_id),
            )

    async def reset_monthly_sessions(self, tenant_id: str) -> None:
        """Reset monthly session counter."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tenants SET sessions_this_month = 0, updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), tenant_id),
            )

    # ── Default Tenant ────────────────────────────────────────────────

    async def ensure_default_tenant(self) -> Tenant:
        """Create default tenant if it doesn't exist.

        Used for on-premise single-tenant installations.
        Plan: ENTERPRISE, always ACTIVE.
        """
        existing = await self.get(self.DEFAULT_TENANT_ID)
        if existing:
            return existing

        default = Tenant(
            id=self.DEFAULT_TENANT_ID,
            name="Default (On-Premise)",
            slug="default",
            plan=TenantPlan.ENTERPRISE,
            status=TenantStatus.ACTIVE,
            config=TenantConfig(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        return await self.create(default)

    # ── License Management ────────────────────────────────────────────

    async def get_license(self, tenant_id: str) -> Optional[TenantLicense]:
        """Get license for a tenant."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM licenses WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
        if not row:
            return None
        return TenantLicense(
            tenant_id=row["tenant_id"],
            plan_name=row["plan_name"],
            projects_total=row["projects_total"],
            projects_activated=row["projects_activated"],
            research_sessions_total=row["research_sessions_total"],
            research_sessions_used=row["research_sessions_used"],
            activated_at=datetime.fromisoformat(row["activated_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            execution_sessions_count=row["execution_sessions_count"],
            purchase_reference=row["purchase_reference"] or "",
            notes=row["notes"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def set_license(self, license: TenantLicense) -> None:
        """Insert or replace a license."""
        license.updated_at = datetime.now()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO licenses
                   (tenant_id, plan_name, projects_total, projects_activated,
                    research_sessions_total, research_sessions_used,
                    activated_at, expires_at, execution_sessions_count,
                    purchase_reference, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    license.tenant_id,
                    license.plan_name,
                    license.projects_total,
                    license.projects_activated,
                    license.research_sessions_total,
                    license.research_sessions_used,
                    license.activated_at.isoformat(),
                    license.expires_at.isoformat() if license.expires_at else None,
                    license.execution_sessions_count,
                    license.purchase_reference,
                    license.notes,
                    license.created_at.isoformat(),
                    license.updated_at.isoformat(),
                ),
            )

    async def activate_project(
        self, tenant_id: str, project_name: str, project_path: str = ""
    ) -> tuple[bool, str]:
        """Activate a project under a tenant license."""
        from config.settings import settings

        lic = await self.get_license(tenant_id)

        # Auto-create license if needed
        if not lic and not settings.multitenant_enabled:
            lic = TenantLicense.create_onpremise(tenant_id)
            await self.set_license(lic)
        elif not lic:
            return False, "Nessuna licenza trovata per questo tenant"

        # Check license allows activation
        can, reason = lic.can_activate_project()
        if not can:
            return False, reason

        # Idempotency: same project_name = already activated
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM activated_projects WHERE tenant_id = ? AND project_name = ?",
                (tenant_id, project_name),
            ).fetchone()

        if existing:
            return True, ""

        # Activate
        import uuid
        lic.projects_activated += 1
        await self.set_license(lic)

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO activated_projects (id, tenant_id, project_name, project_path, activated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (uuid.uuid4().hex[:12], tenant_id, project_name, project_path, datetime.now().isoformat()),
            )

        return True, ""

    async def increment_execution_session(self, tenant_id: str) -> None:
        """Increment execution session counter."""
        lic = await self.get_license(tenant_id)
        if lic:
            lic.execution_sessions_count += 1
            await self.set_license(lic)

    async def increment_research_session(
        self, tenant_id: str
    ) -> tuple[bool, str]:
        """Increment research session counter. Returns (ok, reason)."""
        lic = await self.get_license(tenant_id)
        if not lic:
            return True, ""  # No license = no enforcement

        can, reason = lic.can_use_research()
        if not can:
            return False, reason

        if lic.research_sessions_total != -1:
            lic.research_sessions_used += 1
            await self.set_license(lic)

        return True, ""

    async def upgrade_license(
        self,
        tenant_id: str,
        plan_name: str,
        purchase_reference: str,
        notes: str = "",
    ) -> TenantLicense:
        """Upgrade (or create) a license for a tenant."""
        from datetime import timedelta

        plan = NOXEN_PLANS[plan_name]
        now = datetime.now()
        existing = await self.get_license(tenant_id)

        new_license = TenantLicense(
            tenant_id=tenant_id,
            plan_name=plan_name,
            projects_total=plan.projects_total,
            projects_activated=existing.projects_activated if existing else 0,
            research_sessions_total=plan.research_sessions_total,
            research_sessions_used=0,  # Reset on upgrade
            activated_at=now,
            expires_at=now + timedelta(days=plan.duration_days) if plan.duration_days != -1 else None,
            execution_sessions_count=existing.execution_sessions_count if existing else 0,
            purchase_reference=purchase_reference,
            notes=notes,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )

        await self.set_license(new_license)
        return new_license

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _hash_key(key: str) -> str:
        """SHA-256 hash of API key."""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def _row_to_tenant(row: sqlite3.Row) -> Tenant:
        """Convert SQLite row to Tenant object."""
        config_data = json.loads(row["config_json"])
        return Tenant(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            plan=TenantPlan(row["plan"]),
            status=TenantStatus(row["status"]),
            config=TenantConfig.from_dict(config_data),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            sessions_this_month=row["sessions_this_month"],
            total_sessions=row["total_sessions"],
            total_skills_created=row["total_skills_created"],
        )
