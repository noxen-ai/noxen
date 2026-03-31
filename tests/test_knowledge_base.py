"""Test per core/knowledge_base.py — migrato a Qdrant + FastEmbed.

Testa indicizzazione, ricerca semantica, e hash-based dedup.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.knowledge_base import KnowledgeBase, KnowledgeStatus


# ── Fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def kb(tmp_path: Path):
    """KnowledgeBase con status file in directory temporanea."""
    status_file = tmp_path / "knowledge_status.json"
    with patch("core.knowledge_base.STATUS_FILE", status_file):
        kb_instance = KnowledgeBase()
        yield kb_instance


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Directory skills con file markdown di test."""
    sd = tmp_path / "skills"
    sd.mkdir()

    # Plugin con SKILL.md
    plugin1 = sd / "test-plugin"
    plugin1.mkdir()
    (plugin1 / "SKILL.md").write_text(
        "---\nname: Test Skill\ndescription: A test skill for unit testing\n"
        "tags: [testing, unit]\ncategory: testing\n---\n\n"
        "# Test Skill\n\nThis is a test skill that provides testing capabilities "
        "for Noxen projects. It supports unit testing, integration testing, "
        "and end-to-end testing workflows. This content should be long enough "
        "to pass the minimum character threshold for indexing."
    )

    # Plugin con README.md (> 1KB)
    plugin2 = sd / "another-plugin"
    plugin2.mkdir()
    content = "# Another Plugin\n\n" + "This is documentation content. " * 100
    (plugin2 / "README.md").write_text(content)

    # Agent file
    agents_dir = plugin1 / "agents"
    agents_dir.mkdir()
    (agents_dir / "analyzer.md").write_text(
        "---\nname: Code Analyzer\ndescription: Analyzes code quality\n---\n\n"
        "# Code Analyzer Agent\n\nThis agent analyzes code quality and provides "
        "recommendations for improvement. It checks for code smells, complexity, "
        "and adherence to best practices across multiple programming languages."
    )

    return sd


# ── KnowledgeStatus ──────────────────────────────────────────────────────

class TestKnowledgeStatus:
    """Test per il dataclass KnowledgeStatus."""

    def test_defaults(self):
        """Valori di default corretti."""
        s = KnowledgeStatus()
        assert s.status == "idle"
        assert s.total_files == 0
        assert s.progress_pct == 0.0

    def test_progress_pct(self):
        """progress_pct calcola la percentuale corretta."""
        s = KnowledgeStatus(total_files=10, processed_files=3)
        assert s.progress_pct == 30.0

    def test_progress_pct_zero_files(self):
        """progress_pct ritorna 0 con 0 file."""
        s = KnowledgeStatus(total_files=0)
        assert s.progress_pct == 0.0


# ── Metadata Extraction ─────────────────────────────────────────────────

class TestMetadataExtraction:
    """Test per l'estrazione dei metadati."""

    def test_extract_skill_type(self, kb, skills_dir):
        """File SKILL.md viene classificato come tipo 'skill'."""
        filepath = skills_dir / "test-plugin" / "SKILL.md"
        content = filepath.read_text()
        meta = kb._extract_metadata(filepath, skills_dir, content)
        assert meta["type"] == "skill"
        assert meta["plugin"] == "test-plugin"

    def test_extract_agent_type(self, kb, skills_dir):
        """File nella dir agents/ viene classificato come tipo 'agent'."""
        filepath = skills_dir / "test-plugin" / "agents" / "analyzer.md"
        content = filepath.read_text()
        meta = kb._extract_metadata(filepath, skills_dir, content)
        assert meta["type"] == "agent"

    def test_extract_readme_type(self, kb, skills_dir):
        """README.md viene classificato come tipo 'readme'."""
        filepath = skills_dir / "another-plugin" / "README.md"
        content = filepath.read_text()
        meta = kb._extract_metadata(filepath, skills_dir, content)
        assert meta["type"] == "readme"


# ── Frontmatter Parsing ─────────────────────────────────────────────────

class TestFrontmatter:
    """Test per il parser frontmatter."""

    def test_parse_valid_frontmatter(self):
        """Frontmatter YAML valido viene estratto."""
        content = "---\nname: Test\ndescription: Desc\n---\n\n# Body"
        result = KnowledgeBase._parse_frontmatter(content)
        assert result is not None
        assert result["name"] == "Test"

    def test_parse_with_tags_list(self):
        """Tags come lista inline vengono parsati."""
        content = "---\ntags: [a, b, c]\n---\n\n# Body"
        result = KnowledgeBase._parse_frontmatter(content)
        assert result is not None
        assert result["tags"] == ["a", "b", "c"]

    def test_no_frontmatter(self):
        """Contenuto senza frontmatter ritorna None."""
        result = KnowledgeBase._parse_frontmatter("# No frontmatter here")
        assert result is None

    def test_empty_frontmatter(self):
        """Frontmatter vuoto ritorna None."""
        result = KnowledgeBase._parse_frontmatter("---\n---\n\n# Body")
        assert result is None


# ── Document Preparation ─────────────────────────────────────────────────

class TestDocumentPreparation:
    """Test per _prepare_document()."""

    def test_prepare_normal_document(self, kb):
        """Documento valido viene preparato correttamente."""
        content = "---\nname: Test\n---\n\n" + "x" * 200
        result = kb._prepare_document(content, "test/file.md")
        assert result is not None
        embed_text, store_text = result
        assert "[test/file.md]" in embed_text
        assert len(embed_text) <= 1600  # header + 1500

    def test_prepare_short_document_returns_none(self, kb):
        """Documento troppo corto ritorna None."""
        content = "---\nname: Test\n---\n\nShort"
        result = kb._prepare_document(content, "test/short.md")
        assert result is None

    def test_prepare_strips_frontmatter(self, kb):
        """Il frontmatter viene rimosso dal body."""
        content = "---\nname: Test\n---\n\n" + "Content body here " * 20
        result = kb._prepare_document(content, "test/file.md")
        assert result is not None
        _, store_text = result
        assert "name: Test" not in store_text


# ── File Discovery ───────────────────────────────────────────────────────

class TestFileDiscovery:
    """Test per _discover_md_files()."""

    def test_discovers_skill_md(self, kb, skills_dir):
        """SKILL.md viene trovato."""
        files = kb._discover_md_files(skills_dir)
        skill_files = [f for f in files if f.name == "SKILL.md"]
        assert len(skill_files) == 1

    def test_discovers_agent_files(self, kb, skills_dir):
        """File agent nella directory agents/ vengono trovati."""
        files = kb._discover_md_files(skills_dir)
        agent_files = [f for f in files if "agents" in str(f)]
        assert len(agent_files) >= 1

    def test_discovers_readme(self, kb, skills_dir):
        """README.md viene trovato (se > 1KB)."""
        files = kb._discover_md_files(skills_dir)
        readme_files = [f for f in files if f.name == "README.md"]
        assert len(readme_files) >= 1

    def test_empty_dir_returns_empty(self, kb, tmp_path):
        """Directory vuota ritorna lista vuota."""
        empty = tmp_path / "empty_skills"
        empty.mkdir()
        files = kb._discover_md_files(empty)
        assert files == []


# ── Search ───────────────────────────────────────────────────────────────

class TestSearch:
    """Test per search()."""

    @pytest.mark.asyncio
    async def test_search_empty_kb_returns_empty(self, kb):
        """Search su KB vuota ritorna lista vuota (con Qdrant not initialized)."""
        results = await kb.search("test query")
        assert results == []


# ── Stats ────────────────────────────────────────────────────────────────

class TestStats:
    """Test per get_stats()."""

    def test_stats_default(self, kb):
        """get_stats() ritorna stats di default senza Qdrant."""
        stats = kb.get_stats()
        assert "total_chunks" in stats
        assert "status" in stats
        assert stats["status"] == "idle"


# ── Hash-based Dedup ─────────────────────────────────────────────────────

class TestHashDedup:
    """Test per il meccanismo di deduplicazione hash-based."""

    def test_file_hash_deterministic(self, tmp_path):
        """Lo stesso file produce lo stesso hash."""
        f = tmp_path / "test.md"
        f.write_text("Hello World")
        h1 = KnowledgeBase._file_hash(f)
        h2 = KnowledgeBase._file_hash(f)
        assert h1 == h2

    def test_file_hash_changes(self, tmp_path):
        """File diverso produce hash diverso."""
        f = tmp_path / "test.md"
        f.write_text("Version 1")
        h1 = KnowledgeBase._file_hash(f)
        f.write_text("Version 2")
        h2 = KnowledgeBase._file_hash(f)
        assert h1 != h2
