"""Tenant Model — multitenant data structures.

Phase 8 Step 8.1: Defines Tenant, TenantPlan, TenantConfig,
TenantLimits with plan-based resource constraints.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional


class TenantPlan(str, Enum):
    """Subscription plan with resource limits."""
    FREE = "free"             # 1 project, 10 sessions/month
    PRO = "pro"               # 5 projects, 100 sessions/month
    ENTERPRISE = "enterprise"  # unlimited


class TenantStatus(str, Enum):
    """Tenant lifecycle status."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"


@dataclass
class TenantLimits:
    """Resource limits for a tenant plan."""
    max_projects: int
    max_sessions_per_month: int
    max_sandbox_size_gb: float
    board_providers: List[str]
    notifications_enabled: bool


PLAN_LIMITS: dict[TenantPlan, TenantLimits] = {
    TenantPlan.FREE: TenantLimits(
        max_projects=1,
        max_sessions_per_month=10,
        max_sandbox_size_gb=1.0,
        board_providers=["claude"],
        notifications_enabled=False,
    ),
    TenantPlan.PRO: TenantLimits(
        max_projects=5,
        max_sessions_per_month=100,
        max_sandbox_size_gb=10.0,
        board_providers=["claude", "gemini", "openai"],
        notifications_enabled=True,
    ),
    TenantPlan.ENTERPRISE: TenantLimits(
        max_projects=999,
        max_sessions_per_month=9999,
        max_sandbox_size_gb=100.0,
        board_providers=["claude", "gemini", "openai", "grok", "qwen"],
        notifications_enabled=True,
    ),
}


@dataclass
class TenantConfig:
    """Per-tenant LLM and notification configuration."""
    # LLM
    llm_provider: str = "claude"
    llm_api_key: str = ""
    board_chairman: str = "claude"
    board_enabled: bool = True

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    slack_bot_token: str = ""
    slack_channel_id: str = ""
    google_chat_webhook_url: str = ""
    smtp_host: str = ""
    smtp_to: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantConfig:
        # Filter only known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class Tenant:
    """Complete tenant entity with plan, config, and stats."""
    id: str
    name: str
    slug: str
    plan: TenantPlan
    status: TenantStatus
    config: TenantConfig
    created_at: datetime
    updated_at: datetime

    # Usage stats
    sessions_this_month: int = 0
    total_sessions: int = 0
    total_skills_created: int = 0

    @property
    def limits(self) -> TenantLimits:
        return PLAN_LIMITS[self.plan]

    def can_start_session(self) -> bool:
        """Check if tenant can start a new session."""
        return (
            self.status == TenantStatus.ACTIVE
            and self.sessions_this_month < self.limits.max_sessions_per_month
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "plan": self.plan.value,
            "status": self.status.value,
            "config": self.config.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "sessions_this_month": self.sessions_this_month,
            "total_sessions": self.total_sessions,
            "total_skills_created": self.total_skills_created,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tenant:
        config_data = data.get("config", {})
        if isinstance(config_data, str):
            config_data = json.loads(config_data)

        def parse_dt(val: Any) -> datetime:
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return datetime.now()

        return cls(
            id=data["id"],
            name=data["name"],
            slug=data["slug"],
            plan=TenantPlan(data["plan"]),
            status=TenantStatus(data["status"]),
            config=TenantConfig.from_dict(config_data),
            created_at=parse_dt(data.get("created_at")),
            updated_at=parse_dt(data.get("updated_at")),
            sessions_this_month=data.get("sessions_this_month", 0),
            total_sessions=data.get("total_sessions", 0),
            total_skills_created=data.get("total_skills_created", 0),
        )


# ── Commercial License Model ─────────────────────────────────────────


class TenantLimitError(Exception):
    """Raised when on-premise tenant limit is exceeded."""
    pass


class LicenseError(Exception):
    """Raised on generic license violations."""
    pass


@dataclass
class NoxenPlan:
    """Commercial plan definition."""
    name: str
    projects_total: int          # -1 = unlimited
    duration_days: int           # -1 = unlimited
    board_enabled: bool
    research_sessions_total: int  # -1 = unlimited
    custom_skills: bool
    all_notifications: bool
    price_eur: float


NOXEN_PLANS: dict[str, NoxenPlan] = {
    "trial": NoxenPlan(
        name="trial",
        projects_total=1,
        duration_days=30,
        board_enabled=False,
        research_sessions_total=3,
        custom_skills=False,
        all_notifications=False,
        price_eur=0.0,
    ),
    "starter": NoxenPlan(
        name="starter",
        projects_total=1,
        duration_days=365,
        board_enabled=True,
        research_sessions_total=-1,
        custom_skills=False,
        all_notifications=True,
        price_eur=299.0,
    ),
    "team": NoxenPlan(
        name="team",
        projects_total=5,
        duration_days=365,
        board_enabled=True,
        research_sessions_total=-1,
        custom_skills=True,
        all_notifications=True,
        price_eur=899.0,
    ),
    "scale": NoxenPlan(
        name="scale",
        projects_total=15,
        duration_days=365,
        board_enabled=True,
        research_sessions_total=-1,
        custom_skills=True,
        all_notifications=True,
        price_eur=1999.0,
    ),
    "enterprise": NoxenPlan(
        name="enterprise",
        projects_total=-1,
        duration_days=-1,
        board_enabled=True,
        research_sessions_total=-1,
        custom_skills=True,
        all_notifications=True,
        price_eur=0.0,
    ),
}


@dataclass
class TenantLicense:
    """License assigned to a tenant."""
    tenant_id: str
    plan_name: str
    projects_total: int
    projects_activated: int = 0
    research_sessions_total: int = -1
    research_sessions_used: int = 0
    activated_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    execution_sessions_count: int = 0
    purchase_reference: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def plan(self) -> NoxenPlan:
        return NOXEN_PLANS[self.plan_name]

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    @property
    def is_active(self) -> bool:
        return not self.is_expired

    @property
    def projects_remaining(self) -> int:
        if self.projects_total == -1:
            return 999999
        return max(0, self.projects_total - self.projects_activated)

    @property
    def days_remaining(self) -> Optional[int]:
        if self.expires_at is None:
            return None
        return max(0, (self.expires_at - datetime.now()).days)

    def can_activate_project(self) -> tuple[bool, str]:
        if self.is_expired:
            return False, "Licenza scaduta. Rinnova su noxen.ai/renew"
        if self.projects_remaining == 0:
            return False, (
                f"Hai esaurito i {self.projects_total} progetti. "
                "Upgrade su noxen.ai/upgrade"
            )
        return True, ""

    def can_use_board(self) -> tuple[bool, str]:
        if not self.plan.board_enabled:
            return False, (
                f"Il piano {self.plan_name} non include Board mode. "
                "Upgrade su noxen.ai/upgrade"
            )
        return True, ""

    def can_use_research(self) -> tuple[bool, str]:
        if self.research_sessions_total == -1:
            return True, ""
        if self.research_sessions_used >= self.research_sessions_total:
            return False, (
                f"Hai esaurito le {self.research_sessions_total} sessioni research. "
                "Upgrade su noxen.ai/upgrade"
            )
        return True, ""

    def can_use_custom_skills(self) -> tuple[bool, str]:
        if not self.plan.custom_skills:
            return False, (
                f"Il piano {self.plan_name} non include custom skills. "
                "Upgrade su noxen.ai/upgrade"
            )
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "plan_name": self.plan_name,
            "projects_total": self.projects_total,
            "projects_activated": self.projects_activated,
            "research_sessions_total": self.research_sessions_total,
            "research_sessions_used": self.research_sessions_used,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "execution_sessions_count": self.execution_sessions_count,
            "purchase_reference": self.purchase_reference,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantLicense:
        def _parse_dt(val: Any) -> Optional[datetime]:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return None

        return cls(
            tenant_id=data["tenant_id"],
            plan_name=data["plan_name"],
            projects_total=data["projects_total"],
            projects_activated=data.get("projects_activated", 0),
            research_sessions_total=data.get("research_sessions_total", -1),
            research_sessions_used=data.get("research_sessions_used", 0),
            activated_at=_parse_dt(data.get("activated_at")) or datetime.now(),
            expires_at=_parse_dt(data.get("expires_at")),
            execution_sessions_count=data.get("execution_sessions_count", 0),
            purchase_reference=data.get("purchase_reference", ""),
            notes=data.get("notes", ""),
            created_at=_parse_dt(data.get("created_at")) or datetime.now(),
            updated_at=_parse_dt(data.get("updated_at")) or datetime.now(),
        )

    @classmethod
    def create_trial(cls, tenant_id: str) -> TenantLicense:
        from datetime import timedelta
        plan = NOXEN_PLANS["trial"]
        now = datetime.now()
        return cls(
            tenant_id=tenant_id,
            plan_name="trial",
            projects_total=plan.projects_total,
            research_sessions_total=plan.research_sessions_total,
            activated_at=now,
            expires_at=now + timedelta(days=30),
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def create_onpremise(cls, tenant_id: str) -> TenantLicense:
        plan = NOXEN_PLANS["enterprise"]
        now = datetime.now()
        return cls(
            tenant_id=tenant_id,
            plan_name="enterprise",
            projects_total=plan.projects_total,
            research_sessions_total=plan.research_sessions_total,
            activated_at=now,
            expires_at=None,
            purchase_reference="ON-PREMISE",
            created_at=now,
            updated_at=now,
        )
