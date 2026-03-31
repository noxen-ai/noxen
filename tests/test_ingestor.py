"""Test per core/ingestor.py — migrato a Qdrant + FastEmbed.

Testa file discovery, chunking, e la pipeline di indicizzazione.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from core.ingestor import (
    Ingestor, IndexingProgress, ChunkInfo,
    SOURCE_EXTENSIONS, IMPORTANT_FILENAMES,
)


# ── Fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def mock_pm(tmp_path: Path):
    """ProjectManager mock con un progetto registrato."""
    from core.project_manager import ProjectInfo
    proj_dir = tmp_path / "test-project"
    proj_dir.mkdir()

    pm = MagicMock()
    pm.get.return_value = ProjectInfo(name="test", path=str(proj_dir))
    pm.mark_indexed = MagicMock()
    return pm, proj_dir


@pytest.fixture
def ingestor(mock_pm):
    """Ingestor con ProjectManager mock."""
    pm, _ = mock_pm
    return Ingestor(pm)


@pytest.fixture
def project_with_files(mock_pm) -> tuple:
    """Progetto con file Python per l'indicizzazione."""
    pm, proj_dir = mock_pm

    # Crea file Python
    (proj_dir / "main.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n\n"
        "@app.get('/')\ndef root():\n    return {'status': 'ok'}\n"
    )

    (proj_dir / "utils.py").write_text(
        "def calculate_sum(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "def calculate_product(a: int, b: int) -> int:\n"
        "    return a * b\n"
    )

    # Crea .gitignore
    (proj_dir / ".gitignore").write_text("*.pyc\n__pycache__/\n.env\n")

    # Crea file che dovrebbe essere ignorato
    pycache = proj_dir / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-313.pyc").write_bytes(b"dummy")

    return Ingestor(pm), pm, proj_dir


# ── IndexingProgress ─────────────────────────────────────────────────────

class TestIndexingProgress:
    """Test per il dataclass IndexingProgress."""

    def test_defaults(self):
        p = IndexingProgress(project_name="test")
        assert p.status == "idle"
        assert p.total_files == 0
        assert p.progress_pct == 0.0

    def test_progress_pct(self):
        p = IndexingProgress(project_name="test", total_files=20, processed_files=5)
        assert p.progress_pct == 25.0


# ── File Discovery ───────────────────────────────────────────────────────

class TestFileDiscovery:
    """Test per _scan_dir_sync()."""

    def test_discovers_python_files(self, project_with_files):
        ingestor, _, proj_dir = project_with_files
        files = ingestor._scan_dir_sync(proj_dir)
        py_files = [f for f in files if f.suffix == ".py"]
        assert len(py_files) == 2

    def test_respects_gitignore(self, project_with_files):
        ingestor, _, proj_dir = project_with_files
        # Crea file .env (ignorato da .gitignore)
        (proj_dir / ".env").write_text("SECRET=value")
        files = ingestor._scan_dir_sync(proj_dir)
        env_files = [f for f in files if f.name == ".env"]
        assert len(env_files) == 0

    def test_skips_pycache(self, project_with_files):
        ingestor, _, proj_dir = project_with_files
        files = ingestor._scan_dir_sync(proj_dir)
        pycache_files = [f for f in files if "__pycache__" in str(f)]
        assert len(pycache_files) == 0

    def test_skips_empty_files(self, project_with_files):
        ingestor, _, proj_dir = project_with_files
        (proj_dir / "empty.py").write_text("")
        files = ingestor._scan_dir_sync(proj_dir)
        empty = [f for f in files if f.name == "empty.py"]
        assert len(empty) == 0

    def test_empty_dir(self, ingestor, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        files = ingestor._scan_dir_sync(empty)
        assert files == []


# ── Chunking ─────────────────────────────────────────────────────────────

class TestChunking:
    """Test per _chunk_file()."""

    @pytest.mark.asyncio
    async def test_chunk_small_file(self, project_with_files):
        ingestor, _, proj_dir = project_with_files
        filepath = proj_dir / "utils.py"
        chunks = []
        async for chunk in ingestor._chunk_file(filepath, proj_dir):
            chunks.append(chunk)
        # File piccolo = 1 chunk
        assert len(chunks) == 1
        assert isinstance(chunks[0], ChunkInfo)
        assert chunks[0].language == "python"
        assert chunks[0].file_path == "utils.py"
        assert "calculate_sum" in chunks[0].content

    @pytest.mark.asyncio
    async def test_chunk_preserves_header(self, project_with_files):
        ingestor, _, proj_dir = project_with_files
        filepath = proj_dir / "main.py"
        chunks = []
        async for chunk in ingestor._chunk_file(filepath, proj_dir):
            chunks.append(chunk)
        assert chunks[0].content.startswith("# File: main.py")


# ── Language Detection ───────────────────────────────────────────────────

class TestLanguageDetection:
    """Test per _detect_language()."""

    def test_python(self):
        assert Ingestor._detect_language(Path("test.py")) == "python"

    def test_javascript(self):
        assert Ingestor._detect_language(Path("app.js")) == "javascript"

    def test_typescript(self):
        assert Ingestor._detect_language(Path("component.tsx")) == "typescript"

    def test_unknown(self):
        assert Ingestor._detect_language(Path("file.xyz")) == "text"


# ── Read File Safe ───────────────────────────────────────────────────────

class TestReadFileSafe:
    """Test per _read_file_safe()."""

    def test_read_utf8(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello World", encoding="utf-8")
        assert Ingestor._read_file_safe(f) == "Hello World"

    def test_read_nonexistent(self, tmp_path):
        f = tmp_path / "ghost.txt"
        assert Ingestor._read_file_safe(f) is None

    def test_read_binary_fallback(self, tmp_path):
        f = tmp_path / "binary.txt"
        f.write_bytes(b"\xff\xfe\x00\x00test")
        result = Ingestor._read_file_safe(f)
        assert result is not None  # Should not crash


# ── Search Code ──────────────────────────────────────────────────────────

class TestSearchCode:
    """Test per search_code()."""

    @pytest.mark.asyncio
    async def test_search_no_qdrant_returns_empty(self, ingestor):
        """search_code() senza Qdrant inizializzato ritorna lista vuota."""
        results = await ingestor.search_code("test", "function")
        assert results == []


# ── Source Extensions ────────────────────────────────────────────────────

class TestConstants:
    """Test per le costanti."""

    def test_python_in_source_extensions(self):
        assert ".py" in SOURCE_EXTENSIONS

    def test_dockerfile_in_important_filenames(self):
        assert "Dockerfile" in IMPORTANT_FILENAMES
