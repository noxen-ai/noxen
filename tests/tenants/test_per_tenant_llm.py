"""Test suite per Per-Tenant LLM Config — Step 8.7."""

import pytest
from datetime import datetime
from unittest.mock import patch

from core.llm_provider import LLMProvider
from core.tenants.model import (
    Tenant,
    TenantConfig,
    TenantPlan,
    TenantStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tenant(
    llm_provider="claude",
    llm_api_key="",
    board_chairman="claude",
    board_enabled=True,
) -> Tenant:
    return Tenant(
        id="t-001",
        name="Test Co",
        slug="test",
        plan=TenantPlan.PRO,
        status=TenantStatus.ACTIVE,
        config=TenantConfig(
            llm_provider=llm_provider,
            llm_api_key=llm_api_key,
            board_chairman=board_chairman,
            board_enabled=board_enabled,
        ),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


# ── Tests ────────────────────────────────────────────────────────────

class TestForTenant:
    def test_returns_llm_provider_instance(self):
        """for_tenant returns an LLMProvider."""
        tenant = _make_tenant()
        llm = LLMProvider.for_tenant(tenant)
        assert isinstance(llm, LLMProvider)

    def test_no_api_key_uses_global(self):
        """Without tenant API key, uses global config."""
        tenant = _make_tenant(llm_api_key="")
        llm = LLMProvider.for_tenant(tenant)
        # Should just return a default instance (global settings)
        assert isinstance(llm, LLMProvider)

    def test_with_api_key_overrides_provider(self):
        """With tenant API key, overrides the provider config."""
        tenant = _make_tenant(
            llm_provider="gemini",
            llm_api_key="tenant-gemini-key-123",
        )
        llm = LLMProvider.for_tenant(tenant)
        assert "gemini" in llm._providers
        assert llm._providers["gemini"]["api_key"] == "tenant-gemini-key-123"

    def test_claude_provider_type(self):
        """Claude provider gets type 'claude'."""
        tenant = _make_tenant(
            llm_provider="claude",
            llm_api_key="sk-ant-test",
        )
        llm = LLMProvider.for_tenant(tenant)
        assert llm._providers["claude"]["type"] == "claude"

    def test_openai_provider_type(self):
        """OpenAI provider gets type 'openai'."""
        tenant = _make_tenant(
            llm_provider="openai",
            llm_api_key="sk-test-openai",
        )
        llm = LLMProvider.for_tenant(tenant)
        assert llm._providers["openai"]["type"] == "openai"

    def test_grok_gets_openai_compat_type(self):
        """Grok provider gets type 'openai_compat'."""
        tenant = _make_tenant(
            llm_provider="grok",
            llm_api_key="xai-test-key",
        )
        llm = LLMProvider.for_tenant(tenant)
        assert llm._providers["grok"]["type"] == "openai_compat"

    def test_gemini_provider_type(self):
        """Gemini provider gets type 'gemini'."""
        tenant = _make_tenant(
            llm_provider="gemini",
            llm_api_key="gemini-key",
        )
        llm = LLMProvider.for_tenant(tenant)
        assert llm._providers["gemini"]["type"] == "gemini"

    def test_qwen_gets_openai_compat(self):
        """Qwen gets type 'openai_compat'."""
        tenant = _make_tenant(
            llm_provider="qwen",
            llm_api_key="qwen-key",
        )
        llm = LLMProvider.for_tenant(tenant)
        assert llm._providers["qwen"]["type"] == "openai_compat"


class TestProviderHelpers:
    def test_provider_type_ollama(self):
        assert LLMProvider._provider_type("ollama") == "ollama"

    def test_provider_type_claude(self):
        assert LLMProvider._provider_type("claude") == "claude"

    def test_provider_type_openai(self):
        assert LLMProvider._provider_type("openai") == "openai"

    def test_provider_type_gemini(self):
        assert LLMProvider._provider_type("gemini") == "gemini"

    def test_provider_type_unknown(self):
        assert LLMProvider._provider_type("custom") == "openai_compat"

    def test_default_base_url_openai(self):
        assert "openai.com" in LLMProvider._default_base_url("openai")

    def test_default_base_url_unknown(self):
        assert LLMProvider._default_base_url("unknown") == ""
