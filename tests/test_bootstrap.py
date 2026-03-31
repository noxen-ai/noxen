"""Tests for core/bootstrap.py — Bootstrap Health Checks."""

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.bootstrap import (
    BootstrapResult,
    HealthCheckResult,
    NoxenBootstrap,
)


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def mock_settings(tmp_path):
    """Fake settings with writable tmp dirs."""
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.data_dir = tmp_path / "data"
    s.research_sandbox_dir = str(tmp_path / "sandbox")
    s.github_token = ""
    s.exa_api_key = ""
    s.firecrawl_api_key = ""
    return s


@pytest.fixture
def mock_qdrant_up():
    """Qdrant mock that is healthy."""
    q = AsyncMock()
    q.health_check = AsyncMock(return_value=True)
    return q


@pytest.fixture
def mock_qdrant_down():
    """Qdrant mock that is unreachable."""
    q = AsyncMock()
    q.health_check = AsyncMock(return_value=False)
    return q


@pytest.fixture
def mock_tenant_repo():
    """TenantRepository mock with ensure_default_tenant."""
    repo = AsyncMock()
    tenant = MagicMock()
    tenant.id = "default"
    repo.ensure_default_tenant = AsyncMock(return_value=tenant)
    return repo


# ── Test: _check_internet ────────────────────────────────────────────


def _mock_httpx_ok():
    """Context manager that mocks httpx.AsyncClient for successful internet check."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return patch("core.bootstrap.httpx.AsyncClient", return_value=mock_client)


def _mock_httpx_fail():
    """Context manager that mocks httpx.AsyncClient for failed internet check."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=ConnectionError("no network"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return patch("core.bootstrap.httpx.AsyncClient", return_value=mock_client)


class TestCheckInternet:
    @pytest.mark.asyncio
    async def test_internet_ok(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """_check_internet returns ok when HTTP succeeds."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with _mock_httpx_ok():
            result = await bs._check_internet()
        assert result.status == "ok"
        assert result.required is True
        assert result.name == "internet"

    @pytest.mark.asyncio
    async def test_internet_down(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """_check_internet returns error when HTTP fails."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with _mock_httpx_fail():
            result = await bs._check_internet()
        assert result.status == "error"
        assert result.required is True
        assert "No internet" in result.message

    @pytest.mark.asyncio
    async def test_internet_is_required(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """_check_internet has required=True."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with _mock_httpx_ok():
            result = await bs._check_internet()
        assert result.required is True

    @pytest.mark.asyncio
    async def test_internet_down_run_fails(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """run() with internet down returns success=False."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with _mock_httpx_fail():
            with patch("core.bootstrap.shutil.which", return_value=None):
                with patch("core.embedding_provider.FastEmbedProvider.embed", new_callable=AsyncMock, return_value=[[0.1]]):
                    result = await bs.run()
        assert result.success is False
        assert any("No internet" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_internet_is_first_check(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """_check_internet is the first check in run() results."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.shutil.which", return_value="/usr/bin/claude"):
            with patch("core.embedding_provider.FastEmbedProvider.embed", new_callable=AsyncMock, return_value=[[0.1, 0.2]]):
                mock_settings.github_token = "ghp_x"
                mock_settings.exa_api_key = "exa_x"
                mock_settings.firecrawl_api_key = "fc_x"
                result = await bs.run()
        assert result.checks[0].name == "internet"


# ── Test: _check_qdrant ──────────────────────────────────────────────

class TestCheckQdrant:
    @pytest.mark.asyncio
    async def test_qdrant_ok(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_qdrant()
        assert result.status == "ok"
        assert result.required is True

    @pytest.mark.asyncio
    async def test_qdrant_down(self, mock_settings, mock_qdrant_down, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_down, mock_tenant_repo)
        result = await bs._check_qdrant()
        assert result.status == "error"
        assert result.required is True
        assert "docker-compose" in result.message

    @pytest.mark.asyncio
    async def test_qdrant_exception(self, mock_settings, mock_tenant_repo):
        q = AsyncMock()
        q.health_check = AsyncMock(side_effect=ConnectionError("refused"))
        bs = NoxenBootstrap(mock_settings, q, mock_tenant_repo)
        result = await bs._check_qdrant()
        assert result.status == "error"
        assert "docker-compose" in result.message


# ── Test: _check_claude_cli ──────────────────────────────────────────

class TestCheckClaudeCli:
    @pytest.mark.asyncio
    async def test_claude_in_path(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch.object(shutil, "which", return_value="/usr/local/bin/claude"):
            result = await bs._check_claude_cli()
        assert result.status == "ok"
        assert result.required is False

    @pytest.mark.asyncio
    async def test_claude_not_in_path(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch.object(shutil, "which", return_value=None):
            result = await bs._check_claude_cli()
        assert result.status == "error"
        assert result.required is False
        assert "npm install" in result.message


# ── Test: _check_data_dirs ───────────────────────────────────────────

class TestCheckDataDirs:
    @pytest.mark.asyncio
    async def test_dirs_writable(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_data_dirs()
        assert result.status == "ok"
        assert result.required is True

    @pytest.mark.asyncio
    async def test_dirs_not_writable(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        mock_settings.data_dir = Path("/nonexistent_root_dir_xyz/data")
        mock_settings.research_sandbox_dir = "/nonexistent_root_dir_xyz/sandbox"
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_data_dirs()
        assert result.status == "error"
        assert "non scrivibili" in result.message


# ── Test: _check_default_tenant ──────────────────────────────────────

class TestCheckDefaultTenant:
    @pytest.mark.asyncio
    async def test_tenant_ok(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_default_tenant()
        assert result.status == "ok"
        assert "default" in result.message

    @pytest.mark.asyncio
    async def test_tenant_error(self, mock_settings, mock_qdrant_up):
        repo = AsyncMock()
        repo.ensure_default_tenant = AsyncMock(side_effect=RuntimeError("DB locked"))
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, repo)
        result = await bs._check_default_tenant()
        assert result.status == "error"
        assert "DB locked" in result.message


# ── Test: Optional checks (GitHub, Exa, Firecrawl) ──────────────────

class TestOptionalChecks:
    @pytest.mark.asyncio
    async def test_github_token_missing(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_github_token()
        assert result.status == "warning"
        assert result.required is False

    @pytest.mark.asyncio
    async def test_github_token_present(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        mock_settings.github_token = "ghp_test123"
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_github_token()
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_exa_key_missing(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_exa_key()
        assert result.status == "warning"

    @pytest.mark.asyncio
    async def test_firecrawl_key_missing(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_firecrawl_key()
        assert result.status == "warning"


# ── Test: run() full bootstrap ───────────────────────────────────────

class TestBootstrapRun:
    @pytest.mark.asyncio
    async def test_all_ok(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """All checks pass -> success=True."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.shutil.which", return_value="/usr/bin/claude"):
            with patch("core.embedding_provider.FastEmbedProvider.embed", new_callable=AsyncMock, return_value=[[0.1, 0.2]]):
                mock_settings.github_token = "ghp_x"
                mock_settings.exa_api_key = "exa_x"
                mock_settings.firecrawl_api_key = "fc_x"
                result = await bs.run()
        assert result.success is True
        assert len(result.errors) == 0
        assert len(result.checks) == 11

    @pytest.mark.asyncio
    async def test_qdrant_down_fails(self, mock_settings, mock_qdrant_down, mock_tenant_repo):
        """Qdrant down -> success=False."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_down, mock_tenant_repo)
        with patch("core.bootstrap.shutil.which", return_value=None):
            with patch("core.embedding_provider.FastEmbedProvider.embed", new_callable=AsyncMock, return_value=[[0.1]]):
                result = await bs.run()
        assert result.success is False
        assert len(result.errors) > 0
        assert any("Qdrant" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_optional_missing_still_success(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """Only optional checks failing -> success=True with warnings."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.shutil.which", return_value=None):
            with patch("core.embedding_provider.FastEmbedProvider.embed", new_callable=AsyncMock, return_value=[[0.1]]):
                result = await bs.run()
        assert result.success is True
        assert len(result.warnings) > 0  # claude_cli, github, exa, firecrawl


# ── Test: Health endpoint with bootstrap ─────────────────────────────

class TestHealthEndpoint:
    def test_health_includes_bootstrap(self):
        """GET /api/health includes bootstrap checks."""
        from fastapi.testclient import TestClient
        from main import app
        from tests.conftest import override_tenant_auth

        override_tenant_auth(app)

        # Inject a mock bootstrap result
        app.state.bootstrap_result = BootstrapResult(
            success=True,
            checks=[
                HealthCheckResult(name="qdrant", status="ok", message="OK", required=True),
                HealthCheckResult(name="claude_cli", status="error", message="Not found", required=False),
            ],
            errors=[],
            warnings=["Not found"],
        )

        client = TestClient(app)
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "degraded"
        assert data["version"] == "0.3.0"
        assert data["bootstrap"]["success"] is True
        assert len(data["bootstrap"]["checks"]) == 2
        assert data["bootstrap"]["checks"][0]["name"] == "qdrant"

    def test_health_without_bootstrap(self):
        """GET /api/health works before bootstrap runs."""
        from fastapi.testclient import TestClient
        from main import app
        from tests.conftest import override_tenant_auth

        override_tenant_auth(app)

        # Remove bootstrap result if present
        if hasattr(app.state, "bootstrap_result"):
            delattr(app.state, "bootstrap_result")

        client = TestClient(app)
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["bootstrap"] is None

    def test_health_error_status(self):
        """GET /api/health returns error when bootstrap failed."""
        from fastapi.testclient import TestClient
        from main import app
        from tests.conftest import override_tenant_auth

        override_tenant_auth(app)

        app.state.bootstrap_result = BootstrapResult(
            success=False,
            checks=[
                HealthCheckResult(name="qdrant", status="error", message="Down", required=True),
            ],
            errors=["Down"],
            warnings=[],
        )

        client = TestClient(app)
        r = client.get("/api/health")
        data = r.json()
        assert data["status"] == "error"
        assert data["bootstrap"]["success"] is False
