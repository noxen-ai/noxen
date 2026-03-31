"""Fixture riutilizzabili per i test Noxen."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Aggiungi root progetto al path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Tenant Auth Helpers ──────────────────────────────────────────────

def make_default_tenant_ctx():
    """Create a default on-premise TenantContext for test dependency overrides."""
    from core.tenants.auth import TenantContext
    from core.tenants.model import Tenant, TenantConfig, TenantPlan, TenantStatus

    tenant = Tenant(
        id="default",
        name="Default",
        slug="default",
        plan=TenantPlan.ENTERPRISE,
        status=TenantStatus.ACTIVE,
        config=TenantConfig(),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    return TenantContext(tenant=tenant, tenant_id="default", is_admin=True)


def override_tenant_auth(app):
    """Override get_tenant_context dependency on a FastAPI app for testing."""
    from core.tenants.auth import get_tenant_context, get_public_tenant_context
    ctx = make_default_tenant_ctx()
    app.dependency_overrides[get_tenant_context] = lambda: ctx
    app.dependency_overrides[get_public_tenant_context] = lambda: ctx
    return app


# ── Fixture: directory progetto temporanea ─────────────────────────────

@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Crea una directory temporanea con struttura progetto fake.

    Struttura generata:
      project/
        package.json          (indica JS/Node)
        composer.json          (indica PHP/Laravel)
        .env                   (config DB)
        src/
          index.js
          app.py
        backend/
          requirements.txt     (indica Python)
          main.py
        tests/
          test_example.py
        Dockerfile
        docker-compose.yml
        .github/
          workflows/
            ci.yml
    """
    root = tmp_path / "test-project"
    root.mkdir()

    # Root marker files
    (root / "package.json").write_text(
        '{"name": "test-project", "dependencies": {"express": "^4.18"}}'
    )

    (root / ".env").write_text(
        "DB_HOST=localhost\nDB_PORT=3306\nDB_USER=root\nDB_PASSWORD=secret\nDB_DATABASE=testdb\n"
    )

    # src/
    src = root / "src"
    src.mkdir()
    (src / "index.js").write_text('const express = require("express");\nconst app = express();\n')
    (src / "app.py").write_text('from fastapi import FastAPI\napp = FastAPI()\n')

    # backend/ (Python sub-service)
    backend = root / "backend"
    backend.mkdir()
    (backend / "requirements.txt").write_text("fastapi==0.115.6\nuvicorn==0.34.0\n")
    (backend / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")

    # tests/
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_example.py").write_text("def test_placeholder():\n    assert True\n")

    # Infra
    (root / "Dockerfile").write_text("FROM node:20-alpine\nCOPY . /app\n")
    (root / "docker-compose.yml").write_text("version: '3'\nservices:\n  app:\n    build: .\n")

    # CI
    gh = root / ".github" / "workflows"
    gh.mkdir(parents=True)
    (gh / "ci.yml").write_text("name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n")

    return root


@pytest.fixture
def empty_project_dir(tmp_path: Path) -> Path:
    """Directory vuota (edge case)."""
    d = tmp_path / "empty-project"
    d.mkdir()
    return d


@pytest.fixture
def php_laravel_dir(tmp_path: Path) -> Path:
    """Progetto PHP/Laravel minimale."""
    root = tmp_path / "laravel-app"
    root.mkdir()
    (root / "composer.json").write_text(
        '{"require": {"laravel/framework": "^11.0"}}'
    )
    (root / "artisan").write_text("#!/usr/bin/env php\n")
    app = root / "app"
    app.mkdir()
    (app / "Http").mkdir()
    (app / "Http" / "Controller.php").write_text("<?php\nnamespace App\\Http;\n")

    # .env con DB
    (root / ".env").write_text(
        "DB_HOST=127.0.0.1\nDB_PORT=3306\n"
        "DB_USERNAME=forge\nDB_PASSWORD=pass123\nDB_DATABASE=laravel\n"
    )
    return root


@pytest.fixture
def mock_settings():
    """Settings con valori di test (no Ollama, no API key)."""
    with patch("config.settings") as mock:
        mock.hub_root = Path("/tmp/noxen-test")
        mock.skills_dir = Path("/tmp/noxen-test/skills")
        mock.data_dir = Path("/tmp/noxen-test/data")
        mock.chroma_dir = Path("/tmp/noxen-test/data/chroma")
        mock.ollama_base_url = "http://localhost:11434"
        mock.default_model = "llama3:8b"
        mock.embedding_model = "nomic-embed-text"
        mock.gemini_api_key = ""
        mock.claude_api_key = ""
        mock.openai_api_key = ""
        mock.grok_api_key = ""
        mock.mercury_api_key = ""
        mock.qwen_api_key = ""
        mock.active_provider = "ollama"
        mock.llm_mode = "single"
        mock.board_chairman = "gemini"
        mock.mysql_host = "localhost"
        mock.mysql_port = 3306
        mock.mysql_user = "root"
        mock.mysql_password = ""
        mock.mysql_database = ""
        mock.host = "0.0.0.0"
        mock.port = 8400
        mock.debug = True
        mock.max_file_size_mb = 5
        mock.chunk_size = 1000
        mock.chunk_overlap = 200
        mock.batch_size = 50
        mock.global_ignore = ["node_modules", "__pycache__", ".git", ".venv"]
        yield mock
