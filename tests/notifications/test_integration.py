"""Test suite per integrazione NotificationEngine <-> ExecutionEngine — Step 5.8."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.execution.engine import ExecutionEngine, EngineConfig, EngineState
from core.notifications.engine import NotificationEngine
from core.notifications.base import (
    ApprovalPlan,
    NotificationChannel,
    NotificationResult,
)


# ── Fake channel ─────────────────────────────────────────────────────

class TrackingChannel(NotificationChannel):
    """Channel that tracks all calls for assertions."""

    def __init__(self):
        self.approval_requests: list[ApprovalPlan] = []
        self.notifications: list[tuple[str, str, str]] = []
        self.reminders: list[tuple[ApprovalPlan, int]] = []

    @property
    def name(self) -> str:
        return "tracking"

    def is_configured(self) -> bool:
        return True

    async def send_approval_request(self, plan, actions=None):
        self.approval_requests.append(plan)
        return NotificationResult(success=True, channel="tracking", message_id="t1")

    async def send_notification(self, title, message, level="info"):
        self.notifications.append((title, message, level))
        return NotificationResult(success=True, channel="tracking", message_id="t2")

    async def send_reminder(self, plan, elapsed_minutes):
        self.reminders.append((plan, elapsed_minutes))
        return NotificationResult(success=True, channel="tracking", message_id="t3")


# ── Tests ────────────────────────────────────────────────────────────

class TestNotificationIntegration:
    def test_engine_accepts_notification_engine(self):
        """ExecutionEngine accepts notification_engine param."""
        ne = NotificationEngine()
        engine = ExecutionEngine(
            config=EngineConfig(qdrant_persist=False),
            notification_engine=ne,
        )
        assert engine._notification_engine is ne

    def test_engine_without_notification(self):
        """ExecutionEngine works without notification_engine."""
        engine = ExecutionEngine(config=EngineConfig(qdrant_persist=False))
        assert engine._notification_engine is None

    @pytest.mark.asyncio
    async def test_notify_approval_request(self):
        """_notify_approval_request sends to NotificationEngine."""
        tracking = TrackingChannel()
        ne = NotificationEngine()
        ne.add_channel(tracking)

        engine = ExecutionEngine(
            config=EngineConfig(qdrant_persist=False),
            notification_engine=ne,
        )
        engine.state = EngineState(run_id="r1", project_path="/tmp", project_name="TestP")

        # Setup a simple goal graph
        from core.execution.goal_graph import GoalGraph, GoalNode
        engine.goal_graph = GoalGraph()
        engine.goal_graph.add_goal(GoalNode(id="g1", title="Test Goal", description="do test"))

        await engine._notify_approval_request()

        assert len(tracking.approval_requests) == 1
        plan = tracking.approval_requests[0]
        assert plan.run_id == "r1"
        assert plan.project_name == "TestP"
        assert plan.total_goals == 1
        assert len(plan.goals) == 1
        assert plan.goals[0]["title"] == "Test Goal"

    @pytest.mark.asyncio
    async def test_notify_approval_request_no_engine(self):
        """_notify_approval_request does nothing without notification_engine."""
        engine = ExecutionEngine(config=EngineConfig(qdrant_persist=False))
        engine.state = EngineState(run_id="r1", project_path="/tmp")
        # Should not raise
        await engine._notify_approval_request()

    @pytest.mark.asyncio
    async def test_notify_completion_done(self):
        """_notify_completion sends success notification."""
        tracking = TrackingChannel()
        ne = NotificationEngine()
        ne.add_channel(tracking)

        engine = ExecutionEngine(
            config=EngineConfig(qdrant_persist=False),
            notification_engine=ne,
        )
        engine.state = EngineState(
            run_id="r1", project_path="/tmp",
            project_name="TestP", total_cycles=5,
        )

        from core.execution.goal_graph import GoalGraph, GoalNode, GoalStatus
        engine.goal_graph = GoalGraph()
        engine.goal_graph.add_goal(GoalNode(id="g1", title="G1", description="d"))
        engine.goal_graph.update_status("g1", GoalStatus.DONE)

        await engine._notify_completion("done")

        assert len(tracking.notifications) == 1
        title, message, level = tracking.notifications[0]
        assert "Done" in title
        assert "TestP" in message
        assert level == "success"

    @pytest.mark.asyncio
    async def test_notify_completion_rejected(self):
        """_notify_completion sends warning on rejection."""
        tracking = TrackingChannel()
        ne = NotificationEngine()
        ne.add_channel(tracking)

        engine = ExecutionEngine(
            config=EngineConfig(qdrant_persist=False),
            notification_engine=ne,
        )
        engine.state = EngineState(run_id="r1", project_path="/tmp", project_name="P")

        await engine._notify_completion("rejected")

        assert len(tracking.notifications) == 1
        _, _, level = tracking.notifications[0]
        assert level == "warning"

    @pytest.mark.asyncio
    async def test_notify_completion_no_engine(self):
        """_notify_completion does nothing without notification_engine."""
        engine = ExecutionEngine(config=EngineConfig(qdrant_persist=False))
        engine.state = EngineState(run_id="r1", project_path="/tmp")
        await engine._notify_completion("done")  # no-op

    @pytest.mark.asyncio
    async def test_full_run_with_notifications(self, tmp_path):
        """Full run sends completion notification."""
        tracking = TrackingChannel()
        ne = NotificationEngine()
        ne.add_channel(tracking)

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "main.py").write_text("x = 1\n")

        from core.execution.claude_executor import ExecutionResult

        engine = ExecutionEngine(
            config=EngineConfig(
                qdrant_persist=False,
                require_approval=False,
            ),
            notification_engine=ne,
        )

        # Patch sandbox to avoid real operations
        async def mock_create(path, run_id=""):
            from core.execution.sandbox_manager import SandboxInfo
            return SandboxInfo(
                sandbox_id="s1",
                source_path=str(proj),
                sandbox_path=str(proj),
                branch_name="noxen/test",
                created_at="2026-03-30T00:00:00",
            )

        async def mock_cleanup(sid):
            pass

        engine._sandbox_mgr.create = mock_create
        engine._sandbox_mgr.cleanup = mock_cleanup

        goals = [
            {"id": "g1", "title": "Test", "description": "d", "priority": 1, "category": "fix"},
        ]

        async def mock_gen(ctx):
            return "Do nothing"

        async def mock_exec_fn(instructions, working_dir, goal_id):
            return ExecutionResult(
                goal_id=goal_id,
                instructions=instructions,
                output="Task completed successfully, all changes applied correctly to codebase",
                exit_code=0,
                duration_s=1.0,
                files_changed=["main.py"],
                success=True,
            )

        async def mock_verify(result, title, desc):
            return "si, goal completato"

        engine._executor.generate_instructions = mock_gen
        engine._executor.execute = mock_exec_fn
        engine._executor.verify = mock_verify

        events = []
        async for event in engine.run(str(proj), goals=goals):
            events.append(event)

        # Without approval required, should get completion notification
        assert len(tracking.notifications) == 1
        title, _, level = tracking.notifications[0]
        assert "Done" in title
        assert level == "success"

    @pytest.mark.asyncio
    async def test_notify_approval_request_exception_handled(self):
        """_notify_approval_request handles exceptions gracefully."""
        ne = MagicMock()
        ne.send_approval_request = AsyncMock(side_effect=Exception("boom"))

        engine = ExecutionEngine(
            config=EngineConfig(qdrant_persist=False),
            notification_engine=ne,
        )
        engine.state = EngineState(run_id="r1", project_path="/tmp", project_name="P")

        from core.execution.goal_graph import GoalGraph, GoalNode
        engine.goal_graph = GoalGraph()
        engine.goal_graph.add_goal(GoalNode(id="g1", title="G", description="d"))

        # Should not raise
        await engine._notify_approval_request()

    @pytest.mark.asyncio
    async def test_notify_completion_exception_handled(self):
        """_notify_completion handles exceptions gracefully."""
        ne = MagicMock()
        ne.send_notification = AsyncMock(side_effect=Exception("boom"))

        engine = ExecutionEngine(
            config=EngineConfig(qdrant_persist=False),
            notification_engine=ne,
        )
        engine.state = EngineState(run_id="r1", project_path="/tmp", project_name="P")

        # Should not raise
        await engine._notify_completion("done")
