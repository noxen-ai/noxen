"""Comprehensive licensing tests — Commercial Model.

Tests for TenantLicense, NoxenPlan, and TenantRepository license operations.
"""

import os
import pytest
import tempfile
from datetime import datetime, timedelta

from core.tenants.model import (
    NOXEN_PLANS,
    LicenseError,
    NoxenPlan,
    TenantLicense,
    TenantLimitError,
)


# ── TenantLicense Unit Tests ────────────────────────────────────────


class TestCreateTrial:
    def test_trial_has_expires_at(self):
        lic = TenantLicense.create_trial("t-001")
        assert lic.expires_at is not None
        delta = lic.expires_at - lic.activated_at
        assert 364 <= delta.days <= 365

    def test_trial_plan_name(self):
        lic = TenantLicense.create_trial("t-001")
        assert lic.plan_name == "developer"
        assert lic.projects_total == 1


class TestCreateOnpremise:
    def test_onpremise_no_expiry(self):
        lic = TenantLicense.create_onpremise("default")
        assert lic.expires_at is None

    def test_onpremise_team_plan(self):
        lic = TenantLicense.create_onpremise("default")
        assert lic.plan_name == "team"
        assert lic.purchase_reference == "ON-PREMISE"
        assert lic.projects_total == -1


class TestCanActivateProject:
    def test_false_if_expired(self):
        lic = TenantLicense.create_trial("t-001")
        lic.expires_at = datetime.now() - timedelta(days=1)
        can, reason = lic.can_activate_project()
        assert can is False
        assert "scaduta" in reason.lower() or "Rinnova" in reason

    def test_false_if_no_projects_remaining(self):
        lic = TenantLicense.create_trial("t-001")
        lic.projects_activated = lic.projects_total  # Use all up
        can, reason = lic.can_activate_project()
        assert can is False
        assert "esaurito" in reason.lower() or "Upgrade" in reason

    def test_true_if_active_and_remaining(self):
        lic = TenantLicense.create_trial("t-001")
        can, reason = lic.can_activate_project()
        assert can is True
        assert reason == ""


class TestCanUseBoard:
    def test_false_on_developer(self):
        lic = TenantLicense.create_trial("t-001")
        can, reason = lic.can_use_board()
        assert can is False
        assert "Board" in reason

    def test_true_on_team(self):
        plan = NOXEN_PLANS["team"]
        lic = TenantLicense(
            tenant_id="t-001", plan_name="team",
            projects_total=plan.projects_total,
        )
        can, reason = lic.can_use_board()
        assert can is True


class TestCanUseResearch:
    def test_false_when_exhausted(self):
        lic = TenantLicense.create_trial("t-001")
        lic.research_sessions_used = lic.research_sessions_total
        can, reason = lic.can_use_research()
        assert can is False
        assert "esaurito" in reason.lower() or "ricerche" in reason.lower()

    def test_true_if_unlimited(self):
        lic = TenantLicense.create_onpremise("default")
        can, reason = lic.can_use_research()
        assert can is True
        assert reason == ""


class TestCanUseCustomSkills:
    def test_false_on_developer(self):
        lic = TenantLicense.create_trial("t-001")
        can, reason = lic.can_use_custom_skills()
        assert can is False

    def test_true_on_team(self):
        plan = NOXEN_PLANS["team"]
        lic = TenantLicense(
            tenant_id="t-001", plan_name="team",
            projects_total=plan.projects_total,
        )
        can, _ = lic.can_use_custom_skills()
        assert can is True


class TestCanConfigureLlm:
    def test_false_over_limit_on_developer(self):
        lic = TenantLicense.create_trial("t-001")
        can, reason = lic.can_configure_llm(3)
        assert can is False
        assert "2 provider" in reason

    def test_true_within_limit_on_developer(self):
        lic = TenantLicense.create_trial("t-001")
        can, _ = lic.can_configure_llm(2)
        assert can is True

    def test_true_unlimited_on_team(self):
        lic = TenantLicense.create_onpremise("default")
        can, _ = lic.can_configure_llm(3)
        assert can is True


class TestCanStartExecution:
    def test_true_under_limit_on_developer(self):
        lic = TenantLicense.create_trial("t-001")
        can, _ = lic.can_start_execution(2.5)
        assert can is True

    def test_false_over_limit_on_developer(self):
        lic = TenantLicense.create_trial("t-001")
        can, reason = lic.can_start_execution(3.5)
        assert can is False
        assert "3.0 ore" in reason

    def test_true_unlimited_on_team(self):
        lic = TenantLicense.create_onpremise("default")
        can, _ = lic.can_start_execution(100)
        assert can is True


class TestCanUseRemoteSandbox:
    def test_false_on_developer(self):
        lic = TenantLicense.create_trial("t-001")
        can, reason = lic.can_use_remote_sandbox()
        assert can is False
        assert "sandbox remoto" in reason

    def test_true_on_team(self):
        lic = TenantLicense.create_onpremise("default")
        can, _ = lic.can_use_remote_sandbox()
        assert can is True


class TestProperties:
    def test_is_expired_false_on_onpremise(self):
        lic = TenantLicense.create_onpremise("default")
        assert lic.is_expired is False
        assert lic.is_active is True

    def test_days_remaining_none_on_onpremise(self):
        lic = TenantLicense.create_onpremise("default")
        assert lic.days_remaining is None

    def test_projects_remaining_correct(self):
        lic = TenantLicense.create_trial("t-001")
        assert lic.projects_remaining == 1
        lic.projects_activated = 1
        assert lic.projects_remaining == 0

    def test_projects_remaining_unlimited(self):
        lic = TenantLicense.create_onpremise("default")
        assert lic.projects_remaining == 999999


class TestSerialization:
    def test_to_dict_from_dict_roundtrip(self):
        lic = TenantLicense.create_trial("t-001")
        lic.projects_activated = 1
        lic.research_sessions_used = 2
        lic.execution_sessions_count = 5
        lic.purchase_reference = "REF-123"
        lic.notes = "Test note"

        d = lic.to_dict()
        restored = TenantLicense.from_dict(d)

        assert restored.tenant_id == lic.tenant_id
        assert restored.plan_name == lic.plan_name
        assert restored.projects_total == lic.projects_total
        assert restored.projects_activated == lic.projects_activated
        assert restored.research_sessions_used == lic.research_sessions_used
        assert restored.execution_sessions_count == lic.execution_sessions_count
        assert restored.purchase_reference == lic.purchase_reference
        assert restored.notes == lic.notes
        # expires_at preserved
        assert restored.expires_at is not None
        assert abs((restored.expires_at - lic.expires_at).total_seconds()) < 1

    def test_to_dict_preserves_none_expires(self):
        lic = TenantLicense.create_onpremise("default")
        d = lic.to_dict()
        assert d["expires_at"] is None
        restored = TenantLicense.from_dict(d)
        assert restored.expires_at is None


# ── TenantRepository License Tests ──────────────────────────────────


from core.tenants.repository import TenantRepository
from core.tenants.model import Tenant, TenantConfig, TenantPlan, TenantStatus


def _make_tenant(**kwargs) -> Tenant:
    defaults = dict(
        id="t-001", name="Test Corp", slug="test",
        plan=TenantPlan.PRO, status=TenantStatus.ACTIVE,
        config=TenantConfig(), created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(kwargs)
    return Tenant(**defaults)


@pytest.fixture
def repo(tmp_path):
    db = str(tmp_path / "test_licensing.db")
    return TenantRepository(db_path=db)


class TestActivateProject:
    @pytest.mark.asyncio
    async def test_activate_increments_count(self, repo):
        lic = TenantLicense.create_onpremise("default")
        await repo.set_license(lic)
        ok, _ = await repo.activate_project("default", "myproject", "/path")
        assert ok is True
        updated = await repo.get_license("default")
        assert updated.projects_activated == 1

    @pytest.mark.asyncio
    async def test_activate_idempotent(self, repo):
        lic = TenantLicense.create_onpremise("default")
        await repo.set_license(lic)
        await repo.activate_project("default", "myproject")
        await repo.activate_project("default", "myproject")  # Same name
        updated = await repo.get_license("default")
        assert updated.projects_activated == 1  # Not 2

    @pytest.mark.asyncio
    async def test_activate_fails_if_expired(self, repo):
        lic = TenantLicense.create_trial("t-001")
        lic.expires_at = datetime.now() - timedelta(days=1)
        await repo.set_license(lic)
        ok, reason = await repo.activate_project("t-001", "proj")
        assert ok is False
        assert "scaduta" in reason.lower() or "Rinnova" in reason


class TestUpgradeLicense:
    @pytest.mark.asyncio
    async def test_upgrade_creates_correct_plan(self, repo):
        new_lic = await repo.upgrade_license("t-001", "team", "PUR-001")
        assert new_lic.plan_name == "team"
        assert new_lic.projects_total == -1
        assert new_lic.purchase_reference == "PUR-001"

    @pytest.mark.asyncio
    async def test_upgrade_preserves_activated(self, repo):
        lic = TenantLicense.create_trial("t-001")
        lic.projects_activated = 1
        lic.execution_sessions_count = 10
        await repo.set_license(lic)
        new_lic = await repo.upgrade_license("t-001", "developer", "PUR-002")
        assert new_lic.projects_activated == 1
        assert new_lic.execution_sessions_count == 10
        assert new_lic.research_sessions_used == 0  # Reset


class TestIncrementResearch:
    @pytest.mark.asyncio
    async def test_increment_scales_used(self, repo):
        lic = TenantLicense.create_trial("t-001")
        await repo.set_license(lic)
        ok, _ = await repo.increment_research_session("t-001")
        assert ok is True
        updated = await repo.get_license("t-001")
        assert updated.research_sessions_used == 1

    @pytest.mark.asyncio
    async def test_increment_fails_at_limit(self, repo):
        lic = TenantLicense.create_trial("t-001")
        lic.research_sessions_used = lic.research_sessions_total
        await repo.set_license(lic)
        ok, reason = await repo.increment_research_session("t-001")
        assert ok is False
        assert reason != ""


class TestOnPremiseEnforcement:
    @pytest.mark.asyncio
    async def test_second_tenant_raises(self, repo):
        await repo.create(_make_tenant(id="t-001", slug="first"))
        with pytest.raises(TenantLimitError):
            await repo.create(_make_tenant(id="t-002", slug="second"))

    @pytest.mark.asyncio
    async def test_default_tenant_allowed(self, repo):
        # Default tenant should always be allowed
        await repo.ensure_default_tenant()
        # First non-default tenant should also be allowed
        await repo.create(_make_tenant(id="t-001", slug="first"))


class TestNoxenPlans:
    def test_all_plans_exist(self):
        expected = {"developer", "team"}
        assert set(NOXEN_PLANS.keys()) == expected

    def test_developer_limits(self):
        p = NOXEN_PLANS["developer"]
        assert p.projects_limit == 1
        assert p.llm_providers_limit == 2
        assert p.board_enabled is False
        assert p.execution_hours_day == 3.0
        assert p.research_sessions_month == 50
        assert p.price_eur == 0.0

    def test_team_unlimited(self):
        p = NOXEN_PLANS["team"]
        assert p.projects_limit == -1
        assert p.llm_providers_limit == -1
        assert p.board_enabled is True
        assert p.execution_hours_day == -1
        assert p.research_sessions_month == -1
        assert p.price_eur == 899.0

    def test_create_trial_uses_developer(self):
        lic = TenantLicense.create_trial("t-001")
        assert lic.plan_name == "developer"

    def test_create_onpremise_uses_team(self):
        lic = TenantLicense.create_onpremise("default")
        assert lic.plan_name == "team"


# ── Execution Hours Tests ──────────────────────────────────────────


class TestExecutionHoursRepo:
    @pytest.mark.asyncio
    async def test_get_execution_hours_today_initial(self, repo):
        hours = await repo.get_execution_hours_today("t-001")
        assert hours == 0.0

    @pytest.mark.asyncio
    async def test_add_execution_time_accumulates(self, repo):
        await repo.add_execution_time("t-001", 1.5)
        await repo.add_execution_time("t-001", 0.5)
        hours = await repo.get_execution_hours_today("t-001")
        assert hours == 2.0

    @pytest.mark.asyncio
    async def test_can_start_execution_today_false_after_limit(self, repo):
        # Set up developer license
        lic = TenantLicense.create_trial("t-001")
        await repo.set_license(lic)
        # Add 3 hours
        await repo.add_execution_time("t-001", 3.0)
        can, reason = await repo.can_start_execution_today("t-001")
        assert can is False
        assert "3.0 ore" in reason

    @pytest.mark.asyncio
    async def test_can_start_execution_today_true_under_limit(self, repo):
        lic = TenantLicense.create_trial("t-001")
        await repo.set_license(lic)
        await repo.add_execution_time("t-001", 1.0)
        can, _ = await repo.can_start_execution_today("t-001")
        assert can is True
