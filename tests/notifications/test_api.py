"""Test suite per Notification API routes — Step 5.7."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.notifications import router, init_router
from core.notifications.engine import NotificationEngine, PendingApproval
from core.notifications.base import ApprovalPlan, NotificationResult


# ── Fixtures ─────────────────────────────────────────────────────────

class FakeChannel:
    """Minimal fake channel for API tests."""

    def __init__(self, name="fake", configured=True):
        self._name = name
        self._configured = configured

    @property
    def name(self):
        return self._name

    def is_configured(self):
        return self._configured

    async def send_approval_request(self, plan, actions=None):
        return NotificationResult(success=True, channel=self._name, message_id="m1")

    async def send_notification(self, title, message, level="info"):
        return NotificationResult(success=True, channel=self._name, message_id="m2")

    async def send_reminder(self, plan, elapsed_minutes):
        return NotificationResult(success=True, channel=self._name, message_id="m3")


@pytest.fixture
def notification_engine():
    engine = NotificationEngine()
    engine.add_channel(FakeChannel("test_channel"))
    return engine


@pytest.fixture
def app(notification_engine):
    app = FastAPI()
    app.include_router(router)
    init_router(notification_engine)
    # Override tenant auth for testing (Phase 8)
    from tests.conftest import override_tenant_auth
    override_tenant_auth(app)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def plan():
    return ApprovalPlan(
        run_id="run-1",
        project_name="TestProj",
        goals=[{"title": "G1", "description": "d"}],
        total_goals=1,
        parallel_groups=1,
    )


# ── GET /api/notifications/status ────────────────────────────────────

class TestStatusEndpoint:
    def test_status_initialized(self, client):
        resp = client.get("/api/notifications/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "channels" in data
        assert data["configured_count"] == 1
        assert data["pending_approvals"] == 0

    def test_status_not_initialized(self):
        import api.routes.notifications as mod
        old = mod._notification_engine
        mod._notification_engine = None
        try:
            app = FastAPI()
            app.include_router(router)
            c = TestClient(app)
            resp = c.get("/api/notifications/status")
            assert resp.status_code == 200
            assert resp.json()["status"] == "not_initialized"
        finally:
            mod._notification_engine = old


# ── GET /api/notifications/channels ──────────────────────────────────

class TestChannelsEndpoint:
    def test_list_channels(self, client):
        resp = client.get("/api/notifications/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["channels"]) == 1
        assert data["channels"][0]["name"] == "test_channel"


# ── GET /api/notifications/approvals ─────────────────────────────────

class TestApprovalsEndpoint:
    def test_list_approvals_empty(self, client):
        resp = client.get("/api/notifications/approvals")
        assert resp.status_code == 200
        assert resp.json()["approvals"] == []

    def test_list_approvals_with_pending(self, client, notification_engine, plan):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            notification_engine.send_approval_request(plan)
        )
        resp = client.get("/api/notifications/approvals")
        assert resp.status_code == 200
        approvals = resp.json()["approvals"]
        assert len(approvals) == 1
        assert approvals[0]["project_name"] == "TestProj"


# ── GET /api/notifications/approvals/{id} ────────────────────────────

class TestGetApprovalEndpoint:
    def test_get_approval_found(self, client, notification_engine, plan):
        import asyncio
        pending = asyncio.get_event_loop().run_until_complete(
            notification_engine.send_approval_request(plan)
        )
        resp = client.get(f"/api/notifications/approvals/{pending.approval_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_id"] == pending.approval_id
        assert data["resolved"] is False

    def test_get_approval_not_found(self, client):
        resp = client.get("/api/notifications/approvals/nonexistent")
        assert resp.status_code == 404


# ── POST /api/notifications/approve ──────────────────────────────────

class TestApproveEndpoint:
    def test_approve_success(self, client, notification_engine, plan):
        import asyncio
        pending = asyncio.get_event_loop().run_until_complete(
            notification_engine.send_approval_request(plan)
        )
        resp = client.post(
            "/api/notifications/approve",
            json={"approval_id": pending.approval_id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_approve_not_found(self, client):
        resp = client.post(
            "/api/notifications/approve",
            json={"approval_id": "xxx"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found_or_resolved"


# ── POST /api/notifications/reject ───────────────────────────────────

class TestRejectEndpoint:
    def test_reject_success(self, client, notification_engine, plan):
        import asyncio
        pending = asyncio.get_event_loop().run_until_complete(
            notification_engine.send_approval_request(plan)
        )
        resp = client.post(
            "/api/notifications/reject",
            json={"approval_id": pending.approval_id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"


# ── POST /api/notifications/reminder/{id} ────────────────────────────

class TestReminderEndpoint:
    def test_send_reminder(self, client, notification_engine, plan):
        import asyncio
        pending = asyncio.get_event_loop().run_until_complete(
            notification_engine.send_approval_request(plan)
        )
        resp = client.post(f"/api/notifications/reminder/{pending.approval_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "sent"
        assert len(data["results"]) == 1


# ── POST /api/notifications/test ─────────────────────────────────────

class TestTestEndpoint:
    def test_send_test_notification(self, client):
        resp = client.post(
            "/api/notifications/test",
            json={"title": "Test", "message": "Hello", "level": "info"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "sent"
        assert data["results"][0]["success"] is True

    def test_send_test_default_values(self, client):
        resp = client.post("/api/notifications/test", json={})
        assert resp.status_code == 200
        assert resp.json()["results"][0]["success"] is True

    def test_test_not_initialized(self):
        import api.routes.notifications as mod
        old = mod._notification_engine
        mod._notification_engine = None
        try:
            app = FastAPI()
            app.include_router(router)
            c = TestClient(app)
            resp = c.post("/api/notifications/test", json={})
            assert resp.status_code == 503
        finally:
            mod._notification_engine = old
