"""Test suite per Events API route — Phase 7."""

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.events import router, init_router


@pytest.fixture
def mock_event_router():
    er = MagicMock()
    er.get_recent = MagicMock(return_value=[
        {"id": "e1", "type": "skill_review_completed", "source": "board_reviewer",
         "timestamp": "12:34:56", "data": {"decision": "approve", "skill_id": "s1"}},
        {"id": "e2", "type": "skill_used", "source": "usage_tracker",
         "timestamp": "12:35:00", "data": {"skill_id": "s2", "outcome": "success"}},
        {"id": "e3", "type": "goal_result", "source": "execution_engine",
         "timestamp": "12:36:00", "data": {"goal_title": "Fix bug", "success": True}},
    ])
    return er


@pytest.fixture
def client(mock_event_router):
    app = FastAPI()
    app.include_router(router)
    init_router(event_router=mock_event_router)
    return TestClient(app)


class TestGetRecentEvents:
    def test_returns_all_events(self, client):
        resp = client.get("/api/events/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert len(data["events"]) == 3

    def test_filter_by_type(self, client, mock_event_router):
        # The router filters via get_recent()
        mock_event_router.get_recent = MagicMock(return_value=[
            {"id": "e1", "type": "skill_review_completed", "source": "board_reviewer",
             "timestamp": "12:34:56", "data": {}},
        ])
        resp = client.get("/api/events/recent?type=skill_review_completed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_filter_after_id(self, client):
        resp = client.get("/api/events/recent?after_id=e1")
        assert resp.status_code == 200
        data = resp.json()
        # Should return events after e1 (e2, e3)
        assert data["count"] == 2
        ids = [e["id"] for e in data["events"]]
        assert "e1" not in ids
        assert "e2" in ids

    def test_limit(self, client, mock_event_router):
        resp = client.get("/api/events/recent?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] <= 2

    def test_no_event_router(self):
        app = FastAPI()
        app.include_router(router)
        init_router(event_router=None)
        c = TestClient(app)
        resp = c.get("/api/events/recent")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_empty_events(self, client, mock_event_router):
        mock_event_router.get_recent = MagicMock(return_value=[])
        resp = client.get("/api/events/recent")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
