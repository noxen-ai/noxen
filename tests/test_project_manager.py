"""Test per core/project_manager.py — migrato a Qdrant.

Testa il ciclo CRUD completo, ricerca semantica, e persistenza JSON.
I test con Qdrant richiedono il container in esecuzione.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from core.project_manager import ProjectManager, ProjectInfo, PROJECTS_FILE


# ── Fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def pm(tmp_path: Path):
    """ProjectManager con projects file in directory temporanea."""
    projects_file = tmp_path / "projects.json"
    with patch("core.project_manager.PROJECTS_FILE", projects_file):
        manager = ProjectManager()
        yield manager


@pytest.fixture
def pm_with_project(pm, tmp_path: Path):
    """ProjectManager con un progetto gia' registrato."""
    proj_dir = tmp_path / "my-project"
    proj_dir.mkdir()
    pm.register("my-project", str(proj_dir), description="Test project", tags=["python"])
    return pm, "my-project", proj_dir


# ── ProjectInfo ──────────────────────────────────────────────────────────

class TestProjectInfo:
    """Test per il dataclass ProjectInfo."""

    def test_slug_auto_generated(self):
        """slug viene generato automaticamente dal nome."""
        p = ProjectInfo(name="My Project", path="/tmp")
        assert p.slug == "my_project"

    def test_slug_preserves_explicit(self):
        """slug esplicito non viene sovrascritto."""
        p = ProjectInfo(name="My Project", path="/tmp", slug="custom")
        assert p.slug == "custom"

    def test_defaults(self):
        """Valori di default corretti."""
        p = ProjectInfo(name="test", path="/tmp")
        assert p.description == ""
        assert p.tags == []
        assert p.indexed is False
        assert p.indexed_at == 0.0
        assert p.file_count == 0
        assert p.chunk_count == 0


# ── CRUD ─────────────────────────────────────────────────────────────────

class TestCRUD:
    """Test per il ciclo register/get/list/delete."""

    def test_register_creates_project(self, pm, tmp_path: Path):
        """register() crea il progetto e lo aggiunge al registry."""
        proj_dir = tmp_path / "test-proj"
        proj_dir.mkdir()
        result = pm.register("test-proj", str(proj_dir))
        assert isinstance(result, ProjectInfo)
        assert result.name == "test-proj"

    def test_get_after_register(self, pm_with_project):
        """get() ritorna il progetto registrato."""
        pm, name, _ = pm_with_project
        proj = pm.get(name)
        assert proj is not None
        assert proj.name == name

    def test_get_nonexistent_returns_none(self, pm):
        """get() ritorna None per progetto inesistente."""
        assert pm.get("nonexistent") is None

    def test_list_projects(self, pm_with_project):
        """projects property ritorna il dizionario dei progetti."""
        pm, name, _ = pm_with_project
        projects = pm.projects
        assert name in projects
        assert isinstance(projects[name], ProjectInfo)

    def test_list_empty(self, pm):
        """projects property ritorna dict vuoto senza progetti."""
        assert pm.projects == {}

    def test_unregister_removes_project(self, pm_with_project):
        """unregister() rimuove il progetto."""
        pm, name, _ = pm_with_project
        assert pm.unregister(name) is True
        assert pm.get(name) is None

    def test_unregister_nonexistent_returns_false(self, pm):
        """unregister() ritorna False per progetto inesistente."""
        assert pm.unregister("ghost") is False

    def test_register_invalid_path_raises(self, pm):
        """register() con path inesistente solleva ValueError."""
        with pytest.raises(ValueError, match="non esiste"):
            pm.register("bad", "/nonexistent/path/xyz")

    def test_register_overwrites_existing(self, pm_with_project, tmp_path: Path):
        """register() con lo stesso nome sovrascrive il progetto."""
        pm, name, _ = pm_with_project
        new_dir = tmp_path / "new-dir"
        new_dir.mkdir()
        pm.register(name, str(new_dir), description="Updated")
        proj = pm.get(name)
        assert proj.description == "Updated"
        assert proj.path == str(new_dir)

    def test_full_cycle(self, pm, tmp_path: Path):
        """Ciclo completo: register -> get -> list -> delete."""
        d = tmp_path / "cycle-test"
        d.mkdir()
        pm.register("cycle", str(d))
        assert "cycle" in pm.projects
        assert pm.get("cycle") is not None
        assert pm.unregister("cycle") is True
        assert pm.get("cycle") is None
        assert "cycle" not in pm.projects


# ── Mark Indexed ─────────────────────────────────────────────────────────

class TestMarkIndexed:
    """Test per mark_indexed()."""

    def test_mark_indexed_updates_project(self, pm_with_project):
        """mark_indexed() aggiorna i campi del progetto."""
        pm, name, _ = pm_with_project
        pm.mark_indexed(name, file_count=42, chunk_count=100)
        proj = pm.get(name)
        assert proj.indexed is True
        assert proj.file_count == 42
        assert proj.chunk_count == 100
        assert proj.indexed_at > 0

    def test_mark_indexed_nonexistent_noop(self, pm):
        """mark_indexed() su progetto inesistente non fa nulla."""
        pm.mark_indexed("ghost", 0, 0)  # Non deve lanciare


# ── Persistenza JSON ─────────────────────────────────────────────────────

class TestPersistence:
    """Test per la persistenza JSON locale."""

    def test_save_and_reload(self, tmp_path: Path):
        """I progetti vengono salvati e ricaricati dal JSON."""
        projects_file = tmp_path / "projects.json"
        proj_dir = tmp_path / "persisted"
        proj_dir.mkdir()

        with patch("core.project_manager.PROJECTS_FILE", projects_file):
            pm1 = ProjectManager()
            pm1.register("persisted", str(proj_dir), description="Saved")

        # Nuova istanza — deve ricaricare dal file
        with patch("core.project_manager.PROJECTS_FILE", projects_file):
            pm2 = ProjectManager()
            proj = pm2.get("persisted")
            assert proj is not None
            assert proj.description == "Saved"

    def test_to_dict(self, pm_with_project):
        """to_dict() esporta tutti i progetti come dict."""
        pm, name, _ = pm_with_project
        d = pm.to_dict()
        assert name in d
        assert "name" in d[name]
        assert "path" in d[name]
        assert "indexed" in d[name]


# ── Search Semantica ─────────────────────────────────────────────────────

class TestSearch:
    """Test per la ricerca semantica (search_projects)."""

    @pytest.mark.asyncio
    async def test_search_empty_returns_empty(self, pm):
        """search_projects() su registry vuoto ritorna lista vuota."""
        results = await pm.search_projects("test query")
        assert results == []

    def test_search_code_nonexistent_project(self, pm):
        """search() su progetto inesistente ritorna lista vuota."""
        results = pm.search("ghost", "test")
        assert results == []


# ── Sync to Qdrant ───────────────────────────────────────────────────────

class TestSyncToQdrant:
    """Test per sync_to_qdrant() con Qdrant reale."""

    @pytest.mark.asyncio
    async def test_sync_empty_returns_zero(self, pm):
        """sync_to_qdrant() senza progetti ritorna 0."""
        count = await pm.sync_to_qdrant()
        assert count == 0
