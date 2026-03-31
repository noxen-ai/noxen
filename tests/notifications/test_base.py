"""Test suite per core/notifications/base.py — Step 5.1."""

import pytest
from datetime import datetime

from core.notifications.base import (
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationResult,
    NotificationChannel,
)


# ── ActionType enum ──────────────────────────────────────────────────

class TestActionType:
    def test_values(self):
        assert ActionType.APPROVE == "approve"
        assert ActionType.REJECT == "reject"
        assert ActionType.INFO == "info"
        assert ActionType.REMINDER == "reminder"

    def test_is_str(self):
        assert isinstance(ActionType.APPROVE, str)

    def test_all_members(self):
        assert len(ActionType) == 4


# ── NotificationAction dataclass ────────────────────────────────────

class TestNotificationAction:
    def test_create_minimal(self):
        action = NotificationAction(
            label="Approve",
            action_type=ActionType.APPROVE,
        )
        assert action.label == "Approve"
        assert action.action_type == ActionType.APPROVE
        assert action.url == ""
        assert action.payload == {}

    def test_create_full(self):
        action = NotificationAction(
            label="Reject Plan",
            action_type=ActionType.REJECT,
            url="http://localhost:8400/api/engine/reject",
            payload={"run_id": "abc123"},
        )
        assert action.url == "http://localhost:8400/api/engine/reject"
        assert action.payload["run_id"] == "abc123"

    def test_payload_default_not_shared(self):
        """Each instance gets its own payload dict."""
        a1 = NotificationAction(label="A", action_type=ActionType.INFO)
        a2 = NotificationAction(label="B", action_type=ActionType.INFO)
        a1.payload["x"] = 1
        assert "x" not in a2.payload


# ── ApprovalPlan dataclass ───────────────────────────────────────────

class TestApprovalPlan:
    def test_create_minimal(self):
        plan = ApprovalPlan(run_id="run-1", project_name="MyProject")
        assert plan.run_id == "run-1"
        assert plan.project_name == "MyProject"
        assert plan.goals == []
        assert plan.total_goals == 0
        assert plan.parallel_groups == 0
        assert plan.estimated_time == ""
        assert plan.approve_url == ""
        assert plan.reject_url == ""

    def test_create_full(self):
        plan = ApprovalPlan(
            run_id="run-42",
            project_name="Neural-Hub",
            goals=[
                {"title": "Fix auth", "description": "Repair login flow"},
                {"title": "Add tests", "description": "Unit test coverage"},
            ],
            total_goals=2,
            parallel_groups=1,
            estimated_time="~15 min",
            approve_url="http://localhost:8400/api/engine/approve",
            reject_url="http://localhost:8400/api/engine/reject",
        )
        assert len(plan.goals) == 2
        assert plan.total_goals == 2
        assert plan.estimated_time == "~15 min"

    def test_goals_default_not_shared(self):
        p1 = ApprovalPlan(run_id="a", project_name="A")
        p2 = ApprovalPlan(run_id="b", project_name="B")
        p1.goals.append({"title": "x", "description": "y"})
        assert len(p2.goals) == 0


# ── NotificationResult dataclass ────────────────────────────────────

class TestNotificationResult:
    def test_create_success(self):
        result = NotificationResult(
            success=True,
            channel="telegram",
            message_id="msg-123",
        )
        assert result.success is True
        assert result.channel == "telegram"
        assert result.message_id == "msg-123"
        assert result.error == ""
        assert isinstance(result.timestamp, datetime)

    def test_create_failure(self):
        result = NotificationResult(
            success=False,
            channel="slack",
            error="Connection timeout",
        )
        assert result.success is False
        assert result.error == "Connection timeout"
        assert result.message_id == ""

    def test_raw_response(self):
        result = NotificationResult(
            success=True,
            channel="email",
            raw_response={"status": 250},
        )
        assert result.raw_response["status"] == 250


# ── NotificationChannel ABC ─────────────────────────────────────────

class TestNotificationChannelABC:
    def test_cannot_instantiate(self):
        """ABC cannot be instantiated directly."""
        with pytest.raises(TypeError):
            NotificationChannel()

    def test_concrete_subclass(self):
        """A fully implemented subclass can be instantiated."""

        class DummyChannel(NotificationChannel):
            @property
            def name(self) -> str:
                return "dummy"

            def is_configured(self) -> bool:
                return True

            async def send_approval_request(self, plan, actions=None):
                return NotificationResult(success=True, channel="dummy", message_id="d1")

            async def send_notification(self, title, message, level="info"):
                return NotificationResult(success=True, channel="dummy", message_id="d2")

            async def send_reminder(self, plan, elapsed_minutes):
                return NotificationResult(success=True, channel="dummy", message_id="d3")

        ch = DummyChannel()
        assert ch.name == "dummy"
        assert ch.is_configured() is True

    def test_partial_implementation_fails(self):
        """Subclass missing methods cannot be instantiated."""

        class PartialChannel(NotificationChannel):
            @property
            def name(self) -> str:
                return "partial"

            def is_configured(self) -> bool:
                return False

            # Missing: send_approval_request, send_notification, send_reminder

        with pytest.raises(TypeError):
            PartialChannel()

    @pytest.mark.asyncio
    async def test_concrete_subclass_send(self):
        """Concrete subclass methods work correctly."""

        class TestChannel(NotificationChannel):
            @property
            def name(self) -> str:
                return "test"

            def is_configured(self) -> bool:
                return True

            async def send_approval_request(self, plan, actions=None):
                return NotificationResult(
                    success=True,
                    channel=self.name,
                    message_id=f"approval-{plan.run_id}",
                )

            async def send_notification(self, title, message, level="info"):
                return NotificationResult(
                    success=True,
                    channel=self.name,
                    message_id=f"notif-{title}",
                )

            async def send_reminder(self, plan, elapsed_minutes):
                return NotificationResult(
                    success=True,
                    channel=self.name,
                    message_id=f"reminder-{elapsed_minutes}m",
                )

        ch = TestChannel()
        plan = ApprovalPlan(run_id="test-run", project_name="P")

        r1 = await ch.send_approval_request(plan)
        assert r1.success is True
        assert r1.message_id == "approval-test-run"

        r2 = await ch.send_notification("Title", "Body")
        assert r2.success is True
        assert r2.message_id == "notif-Title"

        r3 = await ch.send_reminder(plan, 30)
        assert r3.success is True
        assert r3.message_id == "reminder-30m"


# ── Package imports ──────────────────────────────────────────────────

class TestPackageImports:
    def test_import_from_package(self):
        from core.notifications import (
            NotificationChannel,
            ActionType,
            ApprovalPlan,
            NotificationAction,
            NotificationResult,
        )
        assert ActionType.APPROVE == "approve"
        assert ApprovalPlan is not None
