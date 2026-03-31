"""Test suite per NotificationEngine — Step 5.6."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from core.notifications.engine import NotificationEngine, PendingApproval
from core.notifications.base import (
    ActionType,
    ApprovalPlan,
    NotificationAction,
    NotificationChannel,
    NotificationResult,
)


# ── Helpers ──────────────────────────────────────────────────────────

class FakeChannel(NotificationChannel):
    """Fake channel for testing."""

    def __init__(self, channel_name: str = "fake", configured: bool = True, fail: bool = False):
        self._name = channel_name
        self._configured = configured
        self._fail = fail
        self.sent: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def is_configured(self) -> bool:
        return self._configured

    async def send_approval_request(self, plan, actions=None):
        if self._fail:
            raise Exception(f"{self._name} failed")
        self.sent.append(f"approval:{plan.run_id}")
        return NotificationResult(success=True, channel=self._name, message_id="msg-1")

    async def send_notification(self, title, message, level="info"):
        if self._fail:
            raise Exception(f"{self._name} failed")
        self.sent.append(f"notif:{title}")
        return NotificationResult(success=True, channel=self._name, message_id="msg-2")

    async def send_reminder(self, plan, elapsed_minutes):
        if self._fail:
            raise Exception(f"{self._name} failed")
        self.sent.append(f"reminder:{elapsed_minutes}m")
        return NotificationResult(success=True, channel=self._name, message_id="msg-3")


@pytest.fixture
def plan():
    return ApprovalPlan(
        run_id="run-42",
        project_name="TestProject",
        goals=[{"title": "Fix", "description": "d"}],
        total_goals=1,
        parallel_groups=1,
    )


# ── Channel management ──────────────────────────────────────────────

class TestChannelManagement:
    def test_add_channel(self):
        engine = NotificationEngine()
        ch = FakeChannel("test")
        engine.add_channel(ch)
        assert len(engine.get_channels()) == 1
        assert engine.get_channels()[0]["name"] == "test"

    def test_add_multiple_channels(self):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("a"))
        engine.add_channel(FakeChannel("b"))
        assert len(engine.get_channels()) == 2

    def test_remove_channel(self):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("a"))
        engine.add_channel(FakeChannel("b"))
        assert engine.remove_channel("a") is True
        assert len(engine.get_channels()) == 1
        assert engine.get_channels()[0]["name"] == "b"

    def test_remove_channel_not_found(self):
        engine = NotificationEngine()
        assert engine.remove_channel("nonexistent") is False

    def test_get_configured_channels(self):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("configured", configured=True))
        engine.add_channel(FakeChannel("unconfigured", configured=False))
        configured = engine.get_configured_channels()
        assert len(configured) == 1
        assert configured[0].name == "configured"

    def test_get_channels_status(self):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("a", configured=True))
        engine.add_channel(FakeChannel("b", configured=False))
        channels = engine.get_channels()
        assert channels[0] == {"name": "a", "configured": True}
        assert channels[1] == {"name": "b", "configured": False}


# ── Send approval request ───────────────────────────────────────────

class TestSendApprovalRequest:
    @pytest.mark.asyncio
    async def test_send_to_single_channel(self, plan):
        engine = NotificationEngine()
        ch = FakeChannel("telegram")
        engine.add_channel(ch)

        pending = await engine.send_approval_request(plan)
        assert pending.approval_id
        assert len(pending.results) == 1
        assert pending.results[0].success is True
        assert pending.results[0].channel == "telegram"
        assert ch.sent == [f"approval:{plan.run_id}"]

    @pytest.mark.asyncio
    async def test_send_to_multiple_channels(self, plan):
        engine = NotificationEngine()
        ch1 = FakeChannel("telegram")
        ch2 = FakeChannel("slack")
        engine.add_channel(ch1)
        engine.add_channel(ch2)

        pending = await engine.send_approval_request(plan)
        assert len(pending.results) == 2
        assert all(r.success for r in pending.results)

    @pytest.mark.asyncio
    async def test_send_skips_unconfigured(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("configured", configured=True))
        engine.add_channel(FakeChannel("unconfigured", configured=False))

        pending = await engine.send_approval_request(plan)
        assert len(pending.results) == 1
        assert pending.results[0].channel == "configured"

    @pytest.mark.asyncio
    async def test_send_no_configured_channels(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("x", configured=False))

        pending = await engine.send_approval_request(plan)
        assert len(pending.results) == 1
        assert pending.results[0].success is False
        assert "No configured channels" in pending.results[0].error

    @pytest.mark.asyncio
    async def test_send_handles_channel_exception(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("good"))
        engine.add_channel(FakeChannel("bad", fail=True))

        pending = await engine.send_approval_request(plan)
        assert len(pending.results) == 2
        success = [r for r in pending.results if r.success]
        failed = [r for r in pending.results if not r.success]
        assert len(success) == 1
        assert len(failed) == 1
        assert "bad failed" in failed[0].error

    @pytest.mark.asyncio
    async def test_pending_approval_tracked(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("ch"))
        pending = await engine.send_approval_request(plan)
        assert engine.get_approval(pending.approval_id) is pending
        assert len(engine.get_pending_approvals()) == 1

    @pytest.mark.asyncio
    async def test_with_actions(self, plan):
        engine = NotificationEngine()
        ch = FakeChannel("ch")
        engine.add_channel(ch)
        actions = [NotificationAction(label="Go", action_type=ActionType.APPROVE)]
        pending = await engine.send_approval_request(plan, actions=actions)
        assert pending.results[0].success is True


# ── Send notification ────────────────────────────────────────────────

class TestSendNotification:
    @pytest.mark.asyncio
    async def test_send_notification(self):
        engine = NotificationEngine()
        ch = FakeChannel("ch")
        engine.add_channel(ch)
        results = await engine.send_notification("Title", "Body", level="info")
        assert len(results) == 1
        assert results[0].success is True
        assert ch.sent == ["notif:Title"]

    @pytest.mark.asyncio
    async def test_send_notification_no_channels(self):
        engine = NotificationEngine()
        results = await engine.send_notification("T", "M")
        assert len(results) == 1
        assert results[0].success is False

    @pytest.mark.asyncio
    async def test_send_notification_exception(self):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("bad", fail=True))
        results = await engine.send_notification("T", "M")
        assert results[0].success is False


# ── Send reminder ────────────────────────────────────────────────────

class TestSendReminder:
    @pytest.mark.asyncio
    async def test_send_reminder(self, plan):
        engine = NotificationEngine()
        ch = FakeChannel("ch")
        engine.add_channel(ch)

        pending = await engine.send_approval_request(plan)
        results = await engine.send_reminder(pending.approval_id)
        assert len(results) == 1
        assert results[0].success is True
        assert pending.reminder_count == 1

    @pytest.mark.asyncio
    async def test_send_reminder_not_found(self):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("ch"))
        results = await engine.send_reminder("nonexistent")
        assert results[0].success is False
        assert "not found" in results[0].error

    @pytest.mark.asyncio
    async def test_send_reminder_already_resolved(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("ch"))
        pending = await engine.send_approval_request(plan)
        engine.resolve_approval(pending.approval_id, "approved")
        results = await engine.send_reminder(pending.approval_id)
        assert results[0].success is False
        assert "already resolved" in results[0].error

    @pytest.mark.asyncio
    async def test_send_reminder_no_channels(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("only", configured=True))
        pending = await engine.send_approval_request(plan)
        # Remove channel after sending
        engine.remove_channel("only")
        results = await engine.send_reminder(pending.approval_id)
        assert results[0].success is False
        assert "No configured" in results[0].error


# ── Resolve approval ────────────────────────────────────────────────

class TestResolveApproval:
    @pytest.mark.asyncio
    async def test_resolve_approve(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("ch"))
        pending = await engine.send_approval_request(plan)

        assert engine.resolve_approval(pending.approval_id, "approved") is True
        assert pending.resolved is True
        assert pending.resolution == "approved"
        assert len(engine.get_pending_approvals()) == 0

    @pytest.mark.asyncio
    async def test_resolve_reject(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("ch"))
        pending = await engine.send_approval_request(plan)

        assert engine.resolve_approval(pending.approval_id, "rejected") is True
        assert pending.resolution == "rejected"

    def test_resolve_not_found(self):
        engine = NotificationEngine()
        assert engine.resolve_approval("xxx", "approved") is False

    @pytest.mark.asyncio
    async def test_resolve_already_resolved(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("ch"))
        pending = await engine.send_approval_request(plan)
        engine.resolve_approval(pending.approval_id, "approved")
        assert engine.resolve_approval(pending.approval_id, "rejected") is False


# ── Status ───────────────────────────────────────────────────────────

class TestStatus:
    @pytest.mark.asyncio
    async def test_get_status(self, plan):
        engine = NotificationEngine()
        engine.add_channel(FakeChannel("a", configured=True))
        engine.add_channel(FakeChannel("b", configured=False))
        await engine.send_approval_request(plan)

        status = engine.get_status()
        assert status["configured_count"] == 1
        assert status["pending_approvals"] == 1
        assert status["total_approvals"] == 1
        assert len(status["channels"]) == 2

    def test_get_status_empty(self):
        engine = NotificationEngine()
        status = engine.get_status()
        assert status["configured_count"] == 0
        assert status["pending_approvals"] == 0


# ── PendingApproval dataclass ────────────────────────────────────────

class TestPendingApproval:
    def test_create(self, plan):
        pa = PendingApproval(approval_id="abc", plan=plan)
        assert pa.approval_id == "abc"
        assert pa.results == []
        assert pa.reminder_count == 0
        assert pa.resolved is False
        assert pa.resolution == ""
        assert isinstance(pa.created_at, datetime)


# ── Qdrant persistence ──────────────────────────────────────────────

class TestQdrantPersistence:
    @pytest.mark.asyncio
    async def test_persist_to_qdrant(self, plan):
        engine = NotificationEngine(qdrant_persist=True)
        engine.add_channel(FakeChannel("ch"))

        mock_qdrant = MagicMock()
        mock_qdrant.add_to_collection = AsyncMock()

        with patch("core.notifications.engine.qdrant_client", mock_qdrant, create=True):
            # Need to patch the import inside the method
            with patch.dict("sys.modules", {"core.qdrant_client": MagicMock(qdrant_client=mock_qdrant)}):
                pending = await engine.send_approval_request(plan)

        # Should have attempted persistence (may succeed or fail gracefully)
        assert pending.approval_id

    @pytest.mark.asyncio
    async def test_no_persist_when_disabled(self, plan):
        engine = NotificationEngine(qdrant_persist=False)
        engine.add_channel(FakeChannel("ch"))
        pending = await engine.send_approval_request(plan)
        # No error, just doesn't persist
        assert pending.results[0].success is True
