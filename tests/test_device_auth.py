# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Noxen. See LICENSE for details.
"""Tests for device auth flow, CLI auth/license commands, and bootstrap license check."""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.bootstrap import HealthCheckResult, NoxenBootstrap


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings(tmp_path):
    """Fake settings for bootstrap tests."""
    s = MagicMock()
    s.noxen_license_key = ""
    s.license_server_url = "https://api.noxen.ai"
    s.license_grace_period_days = 7
    s.data_dir = tmp_path / "data"
    s.research_sandbox_dir = str(tmp_path / "sandbox")
    s.qdrant_url = "http://localhost:6333"
    s.github_token = ""
    s.exa_api_key = ""
    s.firecrawl_api_key = ""
    return s


@pytest.fixture
def mock_qdrant_up():
    q = AsyncMock()
    q.health_check = AsyncMock(return_value=True)
    return q


@pytest.fixture
def mock_tenant_repo():
    repo = AsyncMock()
    tenant = MagicMock()
    tenant.id = "default"
    repo.ensure_default_tenant = AsyncMock(return_value=tenant)
    return repo


# ── _check_license_key tests ───────────────────────────────────────


class TestCheckLicenseKey:
    @pytest.mark.asyncio
    async def test_no_key_returns_warning(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """No license key configured -> warning."""
        mock_settings.noxen_license_key = ""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_license_key()
        assert result.status == "warning"
        assert result.required is False
        assert "noxen auth" in result.message

    @pytest.mark.asyncio
    async def test_valid_key_returns_ok(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """Valid license key -> ok."""
        mock_settings.noxen_license_key = "nxn_test_key_123"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": True, "plan": "starter"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.httpx.AsyncClient", return_value=mock_client):
            result = await bs._check_license_key()
        assert result.status == "ok"
        assert "starter" in result.message

    @pytest.mark.asyncio
    async def test_invalid_key_returns_warning(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """Invalid license key -> warning."""
        mock_settings.noxen_license_key = "nxn_bad_key"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": False}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.httpx.AsyncClient", return_value=mock_client):
            result = await bs._check_license_key()
        assert result.status == "warning"
        assert "non valida" in result.message

    @pytest.mark.asyncio
    async def test_server_unreachable_no_cache(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """Server unreachable + no cache -> warning."""
        mock_settings.noxen_license_key = "nxn_key"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("no network"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.httpx.AsyncClient", return_value=mock_client):
            result = await bs._check_license_key()
        assert result.status == "warning"
        assert "server non raggiungibile" in result.message

    @pytest.mark.asyncio
    async def test_server_unreachable_with_valid_cache(self, mock_settings, mock_qdrant_up, mock_tenant_repo, tmp_path):
        """Server unreachable + valid cache within grace period -> ok."""
        mock_settings.noxen_license_key = "nxn_key"
        mock_settings.data_dir = tmp_path / "data"

        # Create valid cache
        cache_path = mock_settings.data_dir / ".license_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "valid": True,
            "plan": "team",
            "validated_at": time.time() - 3600,  # 1 hour ago
        }
        cache_path.write_text(json.dumps(cache_data))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("no network"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.httpx.AsyncClient", return_value=mock_client):
            result = await bs._check_license_key()
        assert result.status == "ok"
        assert "grace period" in result.message

    @pytest.mark.asyncio
    async def test_server_unreachable_with_expired_cache(self, mock_settings, mock_qdrant_up, mock_tenant_repo, tmp_path):
        """Server unreachable + expired cache -> warning."""
        mock_settings.noxen_license_key = "nxn_key"
        mock_settings.data_dir = tmp_path / "data"
        mock_settings.license_grace_period_days = 7

        # Create expired cache (10 days old)
        cache_path = mock_settings.data_dir / ".license_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "valid": True,
            "plan": "team",
            "validated_at": time.time() - (10 * 86400),  # 10 days ago
        }
        cache_path.write_text(json.dumps(cache_data))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("no network"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.httpx.AsyncClient", return_value=mock_client):
            result = await bs._check_license_key()
        assert result.status == "warning"
        assert "server non raggiungibile" in result.message

    @pytest.mark.asyncio
    async def test_valid_key_creates_cache(self, mock_settings, mock_qdrant_up, mock_tenant_repo, tmp_path):
        """Successful validation creates cache file."""
        mock_settings.noxen_license_key = "nxn_key"
        mock_settings.data_dir = tmp_path / "data"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": True, "plan": "scale"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.httpx.AsyncClient", return_value=mock_client):
            await bs._check_license_key()

        cache_path = mock_settings.data_dir / ".license_cache.json"
        assert cache_path.exists()
        cached = json.loads(cache_path.read_text())
        assert cached["valid"] is True
        assert cached["plan"] == "scale"

    @pytest.mark.asyncio
    async def test_license_check_is_not_required(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """_check_license_key has required=False (server non esiste ancora)."""
        mock_settings.noxen_license_key = ""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        result = await bs._check_license_key()
        assert result.required is False


# ── save_license_key tests ──────────────────────────────────────────


class TestSaveLicenseKey:
    def test_creates_new_env(self, tmp_path):
        """Creates .env if not exists."""
        from cli import save_license_key
        env_file = str(tmp_path / ".env")
        save_license_key("nxn_test_123", env_file=env_file)
        content = Path(env_file).read_text()
        assert "NOXEN_LICENSE_KEY=nxn_test_123" in content

    def test_appends_to_existing_env(self, tmp_path):
        """Appends key to existing .env without NOXEN_LICENSE_KEY."""
        from cli import save_license_key
        env_file = tmp_path / ".env"
        env_file.write_text("NOXEN_DEBUG=true\n")
        save_license_key("nxn_append_key", env_file=str(env_file))
        content = env_file.read_text()
        assert "NOXEN_DEBUG=true" in content
        assert "NOXEN_LICENSE_KEY=nxn_append_key" in content

    def test_replaces_existing_key(self, tmp_path):
        """Replaces existing NOXEN_LICENSE_KEY in .env."""
        from cli import save_license_key
        env_file = tmp_path / ".env"
        env_file.write_text("NOXEN_LICENSE_KEY=old_key\nNOXEN_DEBUG=true\n")
        save_license_key("nxn_new_key", env_file=str(env_file))
        content = env_file.read_text()
        assert "NOXEN_LICENSE_KEY=nxn_new_key" in content
        assert "old_key" not in content
        assert "NOXEN_DEBUG=true" in content


# ── device_auth_flow tests ──────────────────────────────────────────


class TestDeviceAuthFlow:
    @pytest.mark.asyncio
    async def test_flow_returns_key_on_success(self):
        """Full device auth flow returns license key when authorized."""
        from cli import device_auth_flow

        # Mock step 1: device code request
        device_resp = MagicMock()
        device_resp.raise_for_status = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc_123",
            "user_code": "ABCD-1234",
            "verification_url": "https://noxen.ai/activate",
            "expires_in": 10,
            "interval": 0.1,
        }

        # Mock step 3: token polling (authorized on first try)
        token_resp = MagicMock()
        token_resp.json.return_value = {
            "status": "authorized",
            "license_key": "nxn_auth_key_abc",
        }

        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "/v1/auth/device/token" in url:
                return token_resp
            return device_resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cli.httpx.AsyncClient", return_value=mock_client):
            with patch("webbrowser.open"):
                key = await device_auth_flow(
                    server_url="https://api.noxen.ai",
                    timeout_s=5,
                    poll_interval_s=0.1,
                )
        assert key == "nxn_auth_key_abc"

    @pytest.mark.asyncio
    async def test_flow_raises_on_denied(self):
        """Device auth flow raises on denied status."""
        from cli import device_auth_flow

        device_resp = MagicMock()
        device_resp.raise_for_status = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc_123",
            "user_code": "ABCD-1234",
            "verification_url": "https://noxen.ai/activate",
            "expires_in": 10,
            "interval": 0.1,
        }

        token_resp = MagicMock()
        token_resp.json.return_value = {"status": "denied"}

        async def mock_post(url, **kwargs):
            if "/v1/auth/device/token" in url:
                return token_resp
            return device_resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cli.httpx.AsyncClient", return_value=mock_client):
            with patch("webbrowser.open"):
                with pytest.raises(Exception, match="denied"):
                    await device_auth_flow(
                        server_url="https://api.noxen.ai",
                        timeout_s=5,
                        poll_interval_s=0.1,
                    )


# ── Bootstrap run() includes license check ──────────────────────────


class TestBootstrapRunWithLicense:
    @pytest.mark.asyncio
    async def test_license_check_in_run_results(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """run() includes license_key check in results."""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.shutil.which", return_value="/usr/bin/claude"):
            with patch("core.embedding_provider.FastEmbedProvider.embed", new_callable=AsyncMock, return_value=[[0.1, 0.2]]):
                mock_settings.github_token = "ghp_x"
                mock_settings.exa_api_key = "exa_x"
                mock_settings.firecrawl_api_key = "fc_x"
                result = await bs.run()

        check_names = [c.name for c in result.checks]
        assert "license_key" in check_names
        # license_key is second check (after internet)
        assert check_names.index("license_key") == 1

    @pytest.mark.asyncio
    async def test_missing_license_does_not_block(self, mock_settings, mock_qdrant_up, mock_tenant_repo):
        """Missing license key does not prevent bootstrap success."""
        mock_settings.noxen_license_key = ""
        bs = NoxenBootstrap(mock_settings, mock_qdrant_up, mock_tenant_repo)
        with patch("core.bootstrap.shutil.which", return_value=None):
            with patch("core.embedding_provider.FastEmbedProvider.embed", new_callable=AsyncMock, return_value=[[0.1]]):
                result = await bs.run()
        assert result.success is True  # license is not required
