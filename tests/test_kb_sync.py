"""Tests for KB Sync and Session Reporter."""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.kb_sync import KBSync
from core.execution.reporter import SessionReport, SessionReporter, SkillUsageRecord


# ── KBSync Tests ────────────────────────────────────────────────────


class TestKBSyncState:
    def test_load_sync_state_empty(self, tmp_path):
        sync = KBSync(
            license_server_url="http://localhost",
            license_key="test",
            data_dir=str(tmp_path),
        )
        state = sync._load_sync_state()
        assert state == {"last_sync": None, "count": 0}

    def test_save_and_load_state(self, tmp_path):
        sync = KBSync(
            license_server_url="http://localhost",
            license_key="test",
            data_dir=str(tmp_path),
        )
        sync._save_sync_state({
            "last_sync": "2026-01-01T00:00:00",
            "count": 42,
        })
        state = sync._load_sync_state()
        assert state["last_sync"] == "2026-01-01T00:00:00"
        assert state["count"] == 42

    @pytest.mark.asyncio
    async def test_needs_sync_true_if_no_sync(self, tmp_path):
        sync = KBSync(
            license_server_url="http://localhost",
            license_key="test",
            data_dir=str(tmp_path),
        )
        assert await sync.needs_sync() is True

    @pytest.mark.asyncio
    async def test_needs_sync_false_if_recent(self, tmp_path):
        sync = KBSync(
            license_server_url="http://localhost",
            license_key="test",
            data_dir=str(tmp_path),
        )
        sync._save_sync_state({
            "last_sync": (datetime.now() - timedelta(days=1)).isoformat(),
            "count": 10,
        })
        assert await sync.needs_sync() is False

    @pytest.mark.asyncio
    async def test_needs_sync_true_if_old(self, tmp_path):
        sync = KBSync(
            license_server_url="http://localhost",
            license_key="test",
            data_dir=str(tmp_path),
        )
        sync._save_sync_state({
            "last_sync": (datetime.now() - timedelta(days=8)).isoformat(),
            "count": 10,
        })
        assert await sync.needs_sync() is True


class TestKBSyncContribute:
    @pytest.mark.asyncio
    async def test_contribute_false_on_developer(self, tmp_path):
        sync = KBSync(
            license_server_url="http://localhost",
            license_key="test",
            data_dir=str(tmp_path),
        )
        result = await sync.contribute_skill(
            skill_id="s1",
            skill_content={"name": "test"},
            license_key="key",
            plan="developer",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_contribute_attempts_on_team(self, tmp_path):
        sync = KBSync(
            license_server_url="http://localhost:99999",
            license_key="test",
            data_dir=str(tmp_path),
        )
        # Will fail because server is unreachable, but should attempt
        result = await sync.contribute_skill(
            skill_id="s1",
            skill_content={"name": "test"},
            license_key="key",
            plan="team",
        )
        assert result is False  # Server unreachable


# ── SessionReport Tests ────────────────────────────────────────────


class TestSessionReport:
    def _make_report(self, **kwargs) -> SessionReport:
        defaults = dict(
            session_id="sess-001",
            license_key="nh_test",
            plan="developer",
            date="2026-04-01",
            project_type="python",
            technologies=["python", "fastapi"],
            loc_count=5000,
            file_count=42,
            duration_minutes=15.5,
            goals_total=3,
            goals_completed=2,
            goals_failed=1,
            approval_type="manual",
        )
        defaults.update(kwargs)
        return SessionReport(**defaults)

    def test_to_markdown_contains_session_id(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "sess-001" in md

    def test_to_markdown_contains_technologies(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "python" in md
        assert "fastapi" in md

    def test_to_markdown_contains_skills_used(self):
        report = self._make_report(
            skills_used=[SkillUsageRecord("redis-caching", 3, "success")],
        )
        md = report.to_markdown()
        assert "redis-caching" in md
        assert "Skills Used" in md

    def test_to_dict_roundtrip(self):
        report = self._make_report()
        d = report.to_dict()
        assert d["session_id"] == "sess-001"
        assert d["technologies"] == ["python", "fastapi"]
        assert d["goals_total"] == 3
        assert d["goals_completed"] == 2
        assert d["goals_failed"] == 1
        assert d["duration_minutes"] == 15.5

    def test_to_dict_with_skills(self):
        report = self._make_report(
            skills_used=[SkillUsageRecord("test-skill", 2, "partial")],
            skills_created=["new-skill"],
        )
        d = report.to_dict()
        assert len(d["skills_used"]) == 1
        assert d["skills_used"][0]["name"] == "test-skill"
        assert d["skills_created"] == ["new-skill"]


class TestSessionReporter:
    @pytest.mark.asyncio
    async def test_send_saves_local_file(self, tmp_path):
        reporter = SessionReporter(
            license_server_url="http://localhost:99999",
            license_key="test",
            reports_dir=str(tmp_path / "reports"),
        )
        report = SessionReport(
            session_id="local-test",
            license_key="test",
            plan="developer",
            date="2026-04-01",
            project_type="python",
            technologies=["python"],
            loc_count=100,
            file_count=5,
            duration_minutes=2.0,
            goals_total=1,
            goals_completed=1,
            goals_failed=0,
            approval_type="auto",
        )
        result = await reporter.send(report)
        # Server unreachable, so returns False
        assert result is False
        # But local file should exist
        report_path = tmp_path / "reports" / "local-test.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "local-test" in content
        assert "python" in content


# ── Research Agent Skill Repository Tests ──────────────────────────


class TestResearchAgentSkillRepo:
    @pytest.mark.asyncio
    async def test_save_skills_with_repo(self):
        """Research Agent with skill_repository calls save()."""
        from core.research_agent import ResearchAgent
        from core.research.skill_builder import SkillDefinition

        mock_repo = MagicMock()
        mock_repo.save = AsyncMock()

        agent = ResearchAgent(skill_repository=mock_repo)

        skills = [SkillDefinition(
            name="test-skill",
            description="A test skill",
            category="testing",
            content="Test content",
            confidence=0.8,
        )]

        saved = await agent._save_skills(skills, tenant_id="t-001")
        assert saved == 1
        mock_repo.save.assert_called_once()
        saved_skill = mock_repo.save.call_args[0][0]
        assert saved_skill.name == "test-skill"
        assert saved_skill.status.value == "draft"
        assert saved_skill.source.value == "research_agent"

    @pytest.mark.asyncio
    async def test_save_skills_without_repo_uses_kb(self):
        """Research Agent without skill_repository uses KB fallback."""
        from core.research_agent import ResearchAgent
        from core.research.skill_builder import SkillDefinition

        mock_kb = MagicMock()
        mock_kb.add_skill = AsyncMock()

        agent = ResearchAgent(knowledge_base=mock_kb)

        skills = [SkillDefinition(
            name="fallback-skill",
            description="Fallback",
            category="test",
            content="Content",
            confidence=0.5,
        )]

        saved = await agent._save_skills(skills)
        assert saved == 1
        mock_kb.add_skill.assert_called_once()
