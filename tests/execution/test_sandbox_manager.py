"""Test suite per core/execution/sandbox_manager.py — Step 4.1."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from core.execution.sandbox_manager import (
    SandboxManager,
    SandboxInfo,
    EXCLUDE_PATTERNS,
    ENV_FILE_PATTERNS,
    SENSITIVE_KEY_PATTERN,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def sandbox_dir(tmp_path):
    """Directory temporanea per le sandbox."""
    return str(tmp_path / "sandboxes")


@pytest.fixture
def sample_project(tmp_path):
    """Crea un progetto di esempio con struttura tipica."""
    proj = tmp_path / "my_project"
    proj.mkdir()

    # Source files
    (proj / "main.py").write_text("print('hello')\n")
    (proj / "README.md").write_text("# My Project\n")

    # Subdirectory
    src = proj / "src"
    src.mkdir()
    (src / "app.py").write_text("def run(): pass\n")
    (src / "__init__.py").write_text("")

    # Config
    (proj / "requirements.txt").write_text("fastapi\n")

    return proj


@pytest.fixture
def project_with_env(sample_project):
    """Progetto con file .env contenenti segreti."""
    env_content = (
        "DATABASE_URL=postgres://localhost/db\n"
        "API_KEY=sk-super-secret-key-12345\n"
        "SECRET_TOKEN=abc123def456\n"
        "DEBUG=true\n"
        "PORT=8000\n"
        "export AWS_SECRET_KEY=AKIAIOSFODNN7EXAMPLE\n"
        "PASSWORD=my_password_123\n"
        "APP_NAME=myapp\n"
    )
    (sample_project / ".env").write_text(env_content)
    (sample_project / ".env.local").write_text("LOCAL_SECRET_KEY=local123\n")
    return sample_project


@pytest.fixture
def project_with_heavy_dirs(sample_project):
    """Progetto con directory da escludere."""
    (sample_project / "node_modules").mkdir()
    (sample_project / "node_modules" / "big_lib.js").write_text("x" * 1000)
    (sample_project / "__pycache__").mkdir()
    (sample_project / "__pycache__" / "main.cpython-313.pyc").write_bytes(b"\x00" * 100)
    (sample_project / ".venv").mkdir()
    (sample_project / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    return sample_project


@pytest.fixture
def manager(sandbox_dir):
    """SandboxManager con Qdrant disabilitato."""
    return SandboxManager(
        sandbox_base_dir=sandbox_dir,
        qdrant_persist=False,
    )


# ── Test SandboxInfo ─────────────────────────────────────────────────

def test_sandbox_info_to_dict():
    """SandboxInfo.to_dict() produce un dizionario completo."""
    info = SandboxInfo(
        sandbox_id="abc123",
        source_path="/src",
        sandbox_path="/sandbox",
        branch_name="noxen/run-test",
        created_at="2026-03-30T00:00:00",
    )
    d = info.to_dict()
    assert d["sandbox_id"] == "abc123"
    assert d["source_path"] == "/src"
    assert d["status"] == "active"
    assert isinstance(d["sanitized_files"], list)


def test_sandbox_info_default_status():
    """Status di default e' 'active'."""
    info = SandboxInfo(
        sandbox_id="x", source_path="/a", sandbox_path="/b",
        branch_name="br", created_at="now",
    )
    assert info.status == "active"
    assert info.error == ""
    assert info.sanitized_files == []


# ── Test create() ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_sandbox(manager, sample_project):
    """create() copia il progetto e crea la sandbox."""
    info = await manager.create(str(sample_project))
    assert info.status == "active"
    assert info.sandbox_id
    assert info.branch_name.startswith("noxen/run-")

    # Verify files copied
    sandbox = Path(info.sandbox_path)
    assert sandbox.exists()
    assert (sandbox / "main.py").exists()
    assert (sandbox / "README.md").exists()
    assert (sandbox / "src" / "app.py").exists()


@pytest.mark.asyncio
async def test_create_with_custom_run_id(manager, sample_project):
    """create() usa run_id custom se fornito."""
    info = await manager.create(str(sample_project), run_id="custom-123")
    assert info.sandbox_id == "custom-123"
    assert "custom-123" in info.sandbox_path


@pytest.mark.asyncio
async def test_create_nonexistent_path(manager):
    """create() su path inesistente lancia FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        await manager.create("/nonexistent/path/xyz")


@pytest.mark.asyncio
async def test_create_excludes_heavy_dirs(manager, project_with_heavy_dirs):
    """create() esclude node_modules, __pycache__, .venv."""
    info = await manager.create(str(project_with_heavy_dirs))
    sandbox = Path(info.sandbox_path)

    assert not (sandbox / "node_modules").exists()
    assert not (sandbox / "__pycache__").exists()
    assert not (sandbox / ".venv").exists()
    # Ma i file normali ci sono
    assert (sandbox / "main.py").exists()


@pytest.mark.asyncio
async def test_create_inits_git(manager, sample_project):
    """create() inizializza git nella sandbox."""
    info = await manager.create(str(sample_project))
    sandbox = Path(info.sandbox_path)

    assert (sandbox / ".git").exists()


@pytest.mark.asyncio
async def test_create_git_branch(manager, sample_project):
    """create() crea il branch noxen/run-*."""
    info = await manager.create(str(sample_project))
    sandbox = Path(info.sandbox_path)

    # Verify current branch
    import asyncio
    proc = await asyncio.create_subprocess_exec(
        "git", "branch", "--show-current",
        stdout=asyncio.subprocess.PIPE,
        cwd=str(sandbox),
    )
    stdout, _ = await proc.communicate()
    current_branch = stdout.decode().strip()
    assert current_branch == info.branch_name
    assert current_branch.startswith("noxen/run-")


# ── Test env sanitization ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sanitize_env_files(manager, project_with_env):
    """create() sanitizza file .env con chiavi sensibili."""
    info = await manager.create(str(project_with_env))
    sandbox = Path(info.sandbox_path)

    assert len(info.sanitized_files) > 0

    # Check .env content
    env_content = (sandbox / ".env").read_text()
    assert "sk-super-secret-key-12345" not in env_content
    assert "REDACTED_BY_NEURAL_HUB" in env_content
    # Non-sensitive values should remain
    assert "DEBUG=true" in env_content
    assert "PORT=8000" in env_content
    assert "APP_NAME=myapp" in env_content


@pytest.mark.asyncio
async def test_sanitize_preserves_keys(manager, project_with_env):
    """Sanitizzazione mantiene i nomi delle chiavi."""
    info = await manager.create(str(project_with_env))
    sandbox = Path(info.sandbox_path)

    env_content = (sandbox / ".env").read_text()
    assert "API_KEY=" in env_content
    assert "SECRET_TOKEN=" in env_content
    assert "PASSWORD=" in env_content


@pytest.mark.asyncio
async def test_sanitize_export_prefix(manager, project_with_env):
    """Sanitizzazione gestisce 'export' prefix."""
    info = await manager.create(str(project_with_env))
    sandbox = Path(info.sandbox_path)

    env_content = (sandbox / ".env").read_text()
    # export AWS_SECRET_KEY should be redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in env_content
    assert "AWS_SECRET_KEY" in env_content


def test_sensitive_key_pattern_matches():
    """SENSITIVE_KEY_PATTERN matcha chiavi sensibili."""
    test_cases = [
        ("API_KEY=abc123", True),
        ("SECRET_TOKEN=xyz", True),
        ("DATABASE_PASSWORD=pass", True),
        ("export AWS_SECRET_KEY=AKIA", True),
        ("AUTH_TOKEN=tok123", True),
        ("MY_CREDENTIAL=cred", True),
        ("DEBUG=true", False),
        ("PORT=8000", False),
        ("APP_NAME=myapp", False),
        ("DATABASE_URL=postgres://localhost", False),
    ]
    for line, should_match in test_cases:
        match = SENSITIVE_KEY_PATTERN.search(line)
        assert bool(match) == should_match, f"'{line}' match={bool(match)}, expected={should_match}"


# ── Test cleanup ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup(manager, sample_project):
    """cleanup() rimuove la sandbox."""
    info = await manager.create(str(sample_project))
    sandbox_path = Path(info.sandbox_path)
    assert sandbox_path.exists()

    result = await manager.cleanup(info.sandbox_id)
    assert result is True
    assert not sandbox_path.exists()


@pytest.mark.asyncio
async def test_cleanup_nonexistent(manager):
    """cleanup() ritorna False per sandbox inesistente."""
    result = await manager.cleanup("nonexistent-id")
    assert result is False


@pytest.mark.asyncio
async def test_cleanup_removes_from_active(manager, sample_project):
    """cleanup() rimuove dalla lista sandbox attive."""
    info = await manager.create(str(sample_project))
    assert manager.get_sandbox(info.sandbox_id) is not None

    await manager.cleanup(info.sandbox_id)
    assert manager.get_sandbox(info.sandbox_id) is None


@pytest.mark.asyncio
async def test_cleanup_all(manager, sample_project, tmp_path):
    """cleanup_all() rimuove tutte le sandbox."""
    # Create another project for second sandbox
    proj2 = tmp_path / "project2"
    proj2.mkdir()
    (proj2 / "app.py").write_text("x = 1\n")

    info1 = await manager.create(str(sample_project), run_id="run1")
    info2 = await manager.create(str(proj2), run_id="run2")

    assert len(manager.list_sandboxes()) == 2

    count = await manager.cleanup_all()
    assert count == 2
    assert len(manager.list_sandboxes()) == 0


# ── Test get/list ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_sandbox(manager, sample_project):
    """get_sandbox() ritorna info corretta."""
    info = await manager.create(str(sample_project))
    fetched = manager.get_sandbox(info.sandbox_id)
    assert fetched is not None
    assert fetched.sandbox_id == info.sandbox_id
    assert fetched.source_path == str(sample_project.resolve())


@pytest.mark.asyncio
async def test_get_sandbox_not_found(manager):
    """get_sandbox() ritorna None per ID inesistente."""
    assert manager.get_sandbox("nope") is None


@pytest.mark.asyncio
async def test_list_sandboxes(manager, sample_project):
    """list_sandboxes() ritorna tutte le sandbox attive."""
    assert manager.list_sandboxes() == []

    await manager.create(str(sample_project), run_id="s1")
    assert len(manager.list_sandboxes()) == 1

    # Second project
    proj2 = sample_project.parent / "proj2"
    proj2.mkdir()
    (proj2 / "x.py").write_text("pass\n")
    await manager.create(str(proj2), run_id="s2")
    assert len(manager.list_sandboxes()) == 2


# ── Test EXCLUDE_PATTERNS constant ──────────────────────────────────

def test_exclude_patterns_has_common_dirs():
    """EXCLUDE_PATTERNS include le directory comuni da escludere."""
    assert "node_modules" in EXCLUDE_PATTERNS
    assert "__pycache__" in EXCLUDE_PATTERNS
    assert ".git" in EXCLUDE_PATTERNS
    assert ".venv" in EXCLUDE_PATTERNS
    assert "dist" in EXCLUDE_PATTERNS
    assert "build" in EXCLUDE_PATTERNS


# ── Test ENV_FILE_PATTERNS constant ─────────────────────────────────

def test_env_file_patterns():
    """ENV_FILE_PATTERNS include i nomi file env comuni."""
    assert ".env" in ENV_FILE_PATTERNS
    assert ".env.local" in ENV_FILE_PATTERNS
    assert ".env.production" in ENV_FILE_PATTERNS


# ── Test SandboxInfo status transitions ──────────────────────────────

@pytest.mark.asyncio
async def test_sandbox_status_active_on_create(manager, sample_project):
    """Sandbox ha status 'active' dopo creazione."""
    info = await manager.create(str(sample_project))
    assert info.status == "active"


@pytest.mark.asyncio
async def test_sandbox_status_cleaned_after_cleanup(manager, sample_project):
    """Sandbox ha status 'cleaned' dopo cleanup."""
    info = await manager.create(str(sample_project))
    # Get a ref before cleanup removes from dict
    sandbox_info_ref = info
    await manager.cleanup(info.sandbox_id)
    assert sandbox_info_ref.status == "cleaned"


# ── Test Qdrant persist ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_qdrant_persist_called(sample_project, sandbox_dir):
    """Con qdrant_persist=True, _persist_sandbox_info viene chiamata."""
    manager = SandboxManager(
        sandbox_base_dir=sandbox_dir,
        qdrant_persist=True,
    )
    with patch.object(manager, "_persist_sandbox_info", new_callable=AsyncMock) as mock_persist:
        info = await manager.create(str(sample_project))
        mock_persist.assert_called_once()
        call_arg = mock_persist.call_args[0][0]
        assert isinstance(call_arg, SandboxInfo)
        assert call_arg.sandbox_id == info.sandbox_id


@pytest.mark.asyncio
async def test_qdrant_persist_not_called_when_disabled(manager, sample_project):
    """Con qdrant_persist=False, _persist_sandbox_info NON viene chiamata."""
    with patch.object(manager, "_persist_sandbox_info", new_callable=AsyncMock) as mock_persist:
        await manager.create(str(sample_project))
        mock_persist.assert_not_called()


# ── Test edge cases ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_project(manager, tmp_path):
    """create() funziona su progetto vuoto."""
    empty_proj = tmp_path / "empty"
    empty_proj.mkdir()

    info = await manager.create(str(empty_proj))
    assert info.status == "active"
    assert Path(info.sandbox_path).exists()


@pytest.mark.asyncio
async def test_project_with_nested_dirs(manager, tmp_path):
    """create() copia correttamente struttura nidificata."""
    proj = tmp_path / "nested"
    proj.mkdir()
    deep = proj / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep_file.py").write_text("deep = True\n")

    info = await manager.create(str(proj))
    sandbox = Path(info.sandbox_path)
    assert (sandbox / "a" / "b" / "c" / "deep_file.py").exists()


@pytest.mark.asyncio
async def test_sanitize_no_env_files(manager, sample_project):
    """Progetto senza .env non ha file sanitizzati."""
    info = await manager.create(str(sample_project))
    assert info.sanitized_files == []


@pytest.mark.asyncio
async def test_env_without_secrets(manager, tmp_path):
    """File .env senza segreti non viene modificato."""
    proj = tmp_path / "safe_project"
    proj.mkdir()
    (proj / ".env").write_text("DEBUG=true\nPORT=3000\nAPP_NAME=test\n")

    info = await manager.create(str(proj))
    # .env exists but has no secrets — should NOT be in sanitized list
    sandbox = Path(info.sandbox_path)
    env_content = (sandbox / ".env").read_text()
    assert "DEBUG=true" in env_content
    assert "REDACTED_BY_NEURAL_HUB" not in env_content


@pytest.mark.asyncio
async def test_branch_name_format(manager, sample_project):
    """Branch name segue il formato noxen/run-{timestamp}-{id}."""
    info = await manager.create(str(sample_project), run_id="test123456")
    assert info.branch_name.startswith("noxen/run-")
    assert "test12" in info.branch_name  # first 6 chars of run_id
