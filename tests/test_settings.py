"""Test per config/settings.py — configurazione centrale."""

import os
import pytest
from pathlib import Path


class TestSettingsDefaults:
    """Verifica che i valori default siano corretti."""

    def test_settings_loads(self):
        """Settings si carica senza errori."""
        from config.settings import Settings
        s = Settings()
        assert s is not None

    def test_default_port(self):
        """Porta default e' 8400."""
        from config.settings import Settings
        s = Settings()
        assert s.port == 8400

    def test_default_host(self):
        """Host default e' 0.0.0.0."""
        from config.settings import Settings
        s = Settings()
        assert s.host == "0.0.0.0"

    def test_default_ollama_url(self):
        """URL Ollama default e' localhost:11434."""
        from config.settings import Settings
        s = Settings()
        assert s.ollama_base_url == "http://localhost:11434"

    def test_default_model(self):
        """Modello LLM default e' llama3:8b."""
        from config.settings import Settings
        s = Settings()
        assert s.default_model == "llama3:8b"

    def test_default_embedding_model(self):
        """Modello embedding default e' nomic-embed-text."""
        from config.settings import Settings
        s = Settings()
        assert s.embedding_model == "nomic-embed-text"

    def test_default_active_provider(self):
        """Provider attivo default e' ollama."""
        from config.settings import Settings
        s = Settings()
        assert s.active_provider == "ollama"

    def test_default_llm_mode(self):
        """Modalita' LLM default e' single."""
        from config.settings import Settings
        s = Settings()
        assert s.llm_mode == "single"

    def test_api_keys_empty_by_default(self):
        """Tutte le API key sono vuote per default."""
        from config.settings import Settings
        s = Settings()
        assert s.gemini_api_key == ""
        assert s.claude_api_key == ""
        assert s.openai_api_key == ""
        assert s.grok_api_key == ""
        assert s.mercury_api_key == ""
        assert s.qwen_api_key == ""

    def test_paths_are_path_objects(self):
        """I path sono oggetti Path, non stringhe."""
        from config.settings import Settings
        s = Settings()
        assert isinstance(s.hub_root, Path)
        assert isinstance(s.skills_dir, Path)
        assert isinstance(s.data_dir, Path)
        assert isinstance(s.chroma_dir, Path)

    def test_indexing_defaults(self):
        """Parametri indexing hanno valori ragionevoli."""
        from config.settings import Settings
        s = Settings()
        assert s.max_file_size_mb == 5
        assert s.chunk_size == 1000
        assert s.chunk_overlap == 200
        assert s.batch_size == 50

    def test_global_ignore_has_essentials(self):
        """global_ignore contiene le directory essenziali."""
        from config.settings import Settings
        s = Settings()
        assert "node_modules" in s.global_ignore
        assert "__pycache__" in s.global_ignore
        assert ".git" in s.global_ignore
        assert ".venv" in s.global_ignore


class TestSettingsEnvPrefix:
    """Verifica che il prefix NOXEN_ funzioni."""

    def test_env_override_port(self, monkeypatch):
        """NOXEN_PORT sovrascrive il default."""
        monkeypatch.setenv("NOXEN_PORT", "9999")
        from config.settings import Settings
        s = Settings()
        assert s.port == 9999

    def test_env_override_host(self, monkeypatch):
        """NOXEN_HOST sovrascrive il default."""
        monkeypatch.setenv("NOXEN_HOST", "127.0.0.1")
        from config.settings import Settings
        s = Settings()
        assert s.host == "127.0.0.1"

    def test_env_override_debug(self, monkeypatch):
        """NOXEN_DEBUG sovrascrive il default."""
        monkeypatch.setenv("NOXEN_DEBUG", "false")
        from config.settings import Settings
        s = Settings()
        assert s.debug is False

    def test_env_override_api_key(self, monkeypatch):
        """NOXEN_GEMINI_API_KEY sovrascrive il default."""
        monkeypatch.setenv("NOXEN_GEMINI_API_KEY", "test-key-123")
        from config.settings import Settings
        s = Settings()
        assert s.gemini_api_key == "test-key-123"

    def test_env_override_model(self, monkeypatch):
        """NOXEN_DEFAULT_MODEL sovrascrive il default."""
        monkeypatch.setenv("NOXEN_DEFAULT_MODEL", "mistral:latest")
        from config.settings import Settings
        s = Settings()
        assert s.default_model == "mistral:latest"


class TestSettingsNewProviders:
    """Verifica che i nuovi provider (Grok, Mercury, Qwen) siano configurati."""

    def test_grok_defaults(self):
        """Grok ha default corretti."""
        from config.settings import Settings
        s = Settings()
        assert s.grok_model == "grok-4"
        assert s.grok_base_url == "https://api.x.ai/v1"

    def test_mercury_defaults(self):
        """Mercury ha default corretti."""
        from config.settings import Settings
        s = Settings()
        assert s.mercury_model == "mercury-2"
        assert s.mercury_base_url == "https://api.inceptionlabs.ai/v1"

    def test_qwen_defaults(self):
        """Qwen ha default corretti."""
        from config.settings import Settings
        s = Settings()
        assert s.qwen_model == "qwen3-235b-a22b"
        assert "dashscope" in s.qwen_base_url

    def test_board_chairman_default(self):
        """Board chairman default e' gemini."""
        from config.settings import Settings
        s = Settings()
        assert s.board_chairman == "gemini"
