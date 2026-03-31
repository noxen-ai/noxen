"""Test suite per core/research/repo_analyzer.py — Step 3.2 Phase 3."""

import asyncio
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from core.research.repo_analyzer import (
    RepoAnalyzer,
    RepoAnalysis,
    FunctionInfo,
    ClassInfo,
    ImportInfo,
    LANG_EXTENSIONS,
    SKIP_DIRS,
    IMPORTANT_FILENAMES,
    FRAMEWORK_PATTERNS,
)


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def analyzer(tmp_path):
    """RepoAnalyzer con sandbox in tmp_path."""
    return RepoAnalyzer(
        sandbox_dir=str(tmp_path / "sandbox"),
        clone_timeout_s=10,
        max_file_size_kb=256,
    )


@pytest.fixture
def sample_repo(tmp_path):
    """Crea un mini-repo Python per test di analisi."""
    repo = tmp_path / "sample_repo"
    repo.mkdir()

    # Python file con funzioni, classi, import
    (repo / "main.py").write_text(
        'from fastapi import FastAPI\n'
        'import os\n'
        '\n'
        'app = FastAPI()\n'
        '\n'
        'class UserService:\n'
        '    """Gestisce utenti."""\n'
        '    def get_user(self, user_id: int):\n'
        '        pass\n'
        '\n'
        'async def create_user(name: str):\n'
        '    """Crea un utente."""\n'
        '    pass\n'
        '\n'
        '@app.get("/users")\n'
        'async def list_users():\n'
        '    pass\n'
        '\n'
        '@app.post("/users")\n'
        'async def add_user():\n'
        '    pass\n'
    )

    # JS file
    (repo / "index.js").write_text(
        'import express from "express";\n'
        'const app = express();\n'
        '\n'
        'export function hello() {\n'
        '    return "world";\n'
        '}\n'
        '\n'
        'app.get("/api/health", (req, res) => {\n'
        '    res.json({ ok: true });\n'
        '});\n'
    )

    # README
    (repo / "README.md").write_text("# Sample Repo\nA test repository.")

    # requirements.txt
    (repo / "requirements.txt").write_text("fastapi\nuvicorn\n")

    # __pycache__ (should be skipped)
    cache_dir = repo / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "main.cpython-313.pyc").write_bytes(b"\x00\x00")

    return repo


@pytest.fixture
def go_repo(tmp_path):
    """Mini-repo Go."""
    repo = tmp_path / "go_repo"
    repo.mkdir()
    (repo / "main.go").write_text(
        'package main\n'
        '\n'
        'import (\n'
        '    "fmt"\n'
        '    "net/http"\n'
        ')\n'
        '\n'
        'func main() {\n'
        '    fmt.Println("Hello")\n'
        '}\n'
        '\n'
        'func (s *Server) HandleRequest(w http.ResponseWriter, r *http.Request) {\n'
        '    w.Write([]byte("ok"))\n'
        '}\n'
    )
    (repo / "go.mod").write_text("module example.com/test\n\ngo 1.21\n")
    return repo


@pytest.fixture
def java_repo(tmp_path):
    """Mini-repo Java."""
    repo = tmp_path / "java_repo"
    repo.mkdir()
    (repo / "App.java").write_text(
        'import java.util.List;\n'
        'import org.springframework.web.bind.annotation.RestController;\n'
        '\n'
        'public class App extends BaseApp implements Runnable {\n'
        '    public void run() {\n'
        '        System.out.println("Hello");\n'
        '    }\n'
        '\n'
        '    private String getName() {\n'
        '        return "App";\n'
        '    }\n'
        '}\n'
    )
    return repo


# ── Test Dataclasses ────────────────────────────────────────────────

def test_repo_analysis_defaults():
    """RepoAnalysis ha valori default corretti."""
    a = RepoAnalysis(repo_url="https://github.com/o/r")
    assert a.repo_url == "https://github.com/o/r"
    assert a.languages == {}
    assert a.functions == []
    assert a.classes == []
    assert a.imports == []
    assert a.frameworks == []
    assert a.endpoints == []
    assert a.file_count == 0
    assert a.total_lines == 0
    assert a.errors == []


def test_function_info_defaults():
    """FunctionInfo ha valori default corretti."""
    f = FunctionInfo(name="foo", file_path="a.py", language="Python", line_number=1)
    assert f.is_async is False
    assert f.decorators == []
    assert f.docstring == ""


def test_class_info_defaults():
    """ClassInfo ha valori default corretti."""
    c = ClassInfo(name="Foo", file_path="a.py", language="Python", line_number=1)
    assert c.bases == []
    assert c.methods == []
    assert c.docstring == ""


def test_import_info_defaults():
    """ImportInfo ha valori default corretti."""
    i = ImportInfo(module="os", file_path="a.py", language="Python", line_number=1)
    assert i.alias == ""


# ── Test Constants ──────────────────────────────────────────────────

def test_lang_extensions_coverage():
    """LANG_EXTENSIONS copre i linguaggi principali."""
    assert ".py" in LANG_EXTENSIONS
    assert ".js" in LANG_EXTENSIONS
    assert ".ts" in LANG_EXTENSIONS
    assert ".go" in LANG_EXTENSIONS
    assert ".java" in LANG_EXTENSIONS


def test_skip_dirs_has_common():
    """SKIP_DIRS include le directory comuni."""
    assert ".git" in SKIP_DIRS
    assert "__pycache__" in SKIP_DIRS
    assert "node_modules" in SKIP_DIRS


def test_framework_patterns_coverage():
    """FRAMEWORK_PATTERNS copre framework principali."""
    assert "fastapi" in FRAMEWORK_PATTERNS
    assert "express" in FRAMEWORK_PATTERNS
    assert "django" in FRAMEWORK_PATTERNS


# ── Test Language Detection ─────────────────────────────────────────

def test_detect_language_python(analyzer):
    """_detect_language riconosce Python."""
    assert analyzer._detect_language(Path("test.py")) == "Python"


def test_detect_language_js(analyzer):
    """_detect_language riconosce JavaScript."""
    assert analyzer._detect_language(Path("test.js")) == "JavaScript"


def test_detect_language_unknown(analyzer):
    """_detect_language ritorna '' per estensione sconosciuta."""
    assert analyzer._detect_language(Path("test.xyz")) == ""


def test_detect_language_typescript(analyzer):
    """_detect_language riconosce TypeScript (.ts e .tsx)."""
    assert analyzer._detect_language(Path("test.ts")) == "TypeScript"
    assert analyzer._detect_language(Path("test.tsx")) == "TypeScript"


# ── Test Python Analysis ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_python_functions(analyzer, sample_repo):
    """_analyze estrae funzioni Python."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    py_funcs = [f for f in analysis.functions if f.language == "Python"]
    names = [f.name for f in py_funcs]
    assert "create_user" in names
    assert "list_users" in names
    assert "add_user" in names


@pytest.mark.asyncio
async def test_analyze_python_async_detection(analyzer, sample_repo):
    """_analyze detecta funzioni async Python."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    async_funcs = [f for f in analysis.functions if f.language == "Python" and f.is_async]
    assert len(async_funcs) >= 2  # create_user, list_users, add_user


@pytest.mark.asyncio
async def test_analyze_python_classes(analyzer, sample_repo):
    """_analyze estrae classi Python."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    class_names = [c.name for c in analysis.classes if c.language == "Python"]
    assert "UserService" in class_names


@pytest.mark.asyncio
async def test_analyze_python_imports(analyzer, sample_repo):
    """_analyze estrae import Python."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    py_imports = [i for i in analysis.imports if i.language == "Python"]
    modules = [i.module for i in py_imports]
    assert "fastapi" in modules
    assert "os" in modules


@pytest.mark.asyncio
async def test_analyze_python_decorators(analyzer, sample_repo):
    """_analyze estrae decoratori Python."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    decorated = [f for f in analysis.functions if f.decorators]
    assert len(decorated) >= 1  # list_users ha @app.get


# ── Test JS/TS Analysis ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_js_functions(analyzer, sample_repo):
    """_analyze estrae funzioni JavaScript."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    js_funcs = [f for f in analysis.functions if f.language == "JavaScript"]
    names = [f.name for f in js_funcs]
    assert "hello" in names


@pytest.mark.asyncio
async def test_analyze_js_imports(analyzer, sample_repo):
    """_analyze estrae import JavaScript."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    js_imports = [i for i in analysis.imports if i.language == "JavaScript"]
    modules = [i.module for i in js_imports]
    assert "express" in modules


# ── Test Go Analysis ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_go_functions(analyzer, go_repo):
    """_analyze estrae funzioni Go."""
    analysis = await analyzer._analyze(go_repo, "https://github.com/o/r")
    go_funcs = [f for f in analysis.functions if f.language == "Go"]
    names = [f.name for f in go_funcs]
    assert "main" in names
    assert "HandleRequest" in names


@pytest.mark.asyncio
async def test_analyze_go_imports(analyzer, go_repo):
    """_analyze estrae import Go."""
    analysis = await analyzer._analyze(go_repo, "https://github.com/o/r")
    go_imports = [i for i in analysis.imports if i.language == "Go"]
    modules = [i.module for i in go_imports]
    assert "fmt" in modules
    assert "net/http" in modules


# ── Test Java Analysis ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_java_classes(analyzer, java_repo):
    """_analyze estrae classi Java."""
    analysis = await analyzer._analyze(java_repo, "https://github.com/o/r")
    java_classes = [c for c in analysis.classes if c.language == "Java"]
    names = [c.name for c in java_classes]
    assert "App" in names
    # Check bases
    app_class = next(c for c in java_classes if c.name == "App")
    assert "BaseApp" in app_class.bases
    assert "Runnable" in app_class.bases


@pytest.mark.asyncio
async def test_analyze_java_methods(analyzer, java_repo):
    """_analyze estrae metodi Java."""
    analysis = await analyzer._analyze(java_repo, "https://github.com/o/r")
    java_funcs = [f for f in analysis.functions if f.language == "Java"]
    names = [f.name for f in java_funcs]
    assert "run" in names
    assert "getName" in names


@pytest.mark.asyncio
async def test_analyze_java_imports(analyzer, java_repo):
    """_analyze estrae import Java."""
    analysis = await analyzer._analyze(java_repo, "https://github.com/o/r")
    java_imports = [i for i in analysis.imports if i.language == "Java"]
    modules = [i.module for i in java_imports]
    assert "java.util.List" in modules


# ── Test Framework Detection ───────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_fastapi(analyzer, sample_repo):
    """_analyze detecta FastAPI."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    assert "fastapi" in analysis.frameworks


@pytest.mark.asyncio
async def test_detect_express(analyzer, sample_repo):
    """_analyze detecta Express."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    assert "express" in analysis.frameworks


# ── Test Endpoint Extraction ───────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_fastapi_endpoints(analyzer, sample_repo):
    """_analyze estrae endpoint FastAPI."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    paths = [e["path"] for e in analysis.endpoints]
    assert "/users" in paths


@pytest.mark.asyncio
async def test_extract_express_endpoints(analyzer, sample_repo):
    """_analyze estrae endpoint Express."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    paths = [e["path"] for e in analysis.endpoints]
    assert "/api/health" in paths


# ── Test Important Files ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_important_files_detected(analyzer, sample_repo):
    """_analyze trova i file importanti."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    assert "README.md" in analysis.important_files
    assert "requirements.txt" in analysis.important_files


# ── Test Skip Dirs ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skips_pycache(analyzer, sample_repo):
    """_analyze salta __pycache__."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    # No files from __pycache__ should appear
    all_files = [f.file_path for f in analysis.functions]
    all_files += [c.file_path for c in analysis.classes]
    for fp in all_files:
        assert "__pycache__" not in fp


# ── Test File Count / Lines ────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_count(analyzer, sample_repo):
    """_analyze conta i file analizzati."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    assert analysis.file_count >= 2  # main.py + index.js


@pytest.mark.asyncio
async def test_total_lines(analyzer, sample_repo):
    """_analyze conta le righe totali."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    assert analysis.total_lines > 0


@pytest.mark.asyncio
async def test_languages_count(analyzer, sample_repo):
    """_analyze conta i linguaggi."""
    analysis = await analyzer._analyze(sample_repo, "https://github.com/o/r")
    assert "Python" in analysis.languages
    assert "JavaScript" in analysis.languages


# ── Test Max File Size ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skips_large_files(analyzer, tmp_path):
    """_analyze salta file piu' grandi di max_file_size."""
    repo = tmp_path / "big_repo"
    repo.mkdir()
    # 1MB file (analyzer max is 256KB)
    (repo / "huge.py").write_text("x = 1\n" * 200000)
    (repo / "small.py").write_text("y = 2\n")

    analysis = await analyzer._analyze(repo, "https://github.com/o/r")
    assert analysis.file_count == 1  # solo small.py


# ── Test Clone & Analyze (mocked) ──────────────────────────────────

@pytest.mark.asyncio
async def test_clone_and_analyze_success(analyzer, sample_repo):
    """clone_and_analyze con clone mockato ritorna analisi completa."""
    with patch.object(analyzer, "_clone", new_callable=AsyncMock, return_value=sample_repo):
        with patch.object(analyzer, "_cleanup"):
            analysis = await analyzer.clone_and_analyze("https://github.com/o/r")

    assert analysis.repo_url == "https://github.com/o/r"
    assert analysis.file_count >= 2
    assert len(analysis.errors) == 0


@pytest.mark.asyncio
async def test_clone_and_analyze_timeout(analyzer):
    """clone_and_analyze gestisce timeout."""
    with patch.object(analyzer, "_clone", new_callable=AsyncMock, side_effect=asyncio.TimeoutError):
        analysis = await analyzer.clone_and_analyze("https://github.com/o/r")

    assert len(analysis.errors) > 0
    assert "timeout" in analysis.errors[0].lower()


@pytest.mark.asyncio
async def test_clone_and_analyze_error(analyzer):
    """clone_and_analyze gestisce errori generici."""
    with patch.object(analyzer, "_clone", new_callable=AsyncMock, side_effect=RuntimeError("clone failed")):
        analysis = await analyzer.clone_and_analyze("https://github.com/o/r")

    assert len(analysis.errors) > 0
    assert "clone failed" in analysis.errors[0]


@pytest.mark.asyncio
async def test_clone_and_analyze_cleanup_called(analyzer, sample_repo):
    """clone_and_analyze chiama cleanup dopo analisi."""
    with patch.object(analyzer, "_clone", new_callable=AsyncMock, return_value=sample_repo):
        with patch.object(analyzer, "_cleanup") as mock_cleanup:
            await analyzer.clone_and_analyze("https://github.com/o/r")

    mock_cleanup.assert_called_once_with(sample_repo)


# ── Test Cleanup ───────────────────────────────────────────────────

def test_cleanup_removes_directory(analyzer, tmp_path):
    """_cleanup rimuove la directory."""
    target = tmp_path / "to_clean" / "repo"
    target.mkdir(parents=True)
    (target / "file.txt").write_text("test")

    analyzer._cleanup(target)
    assert not (tmp_path / "to_clean").exists()


def test_cleanup_handles_nonexistent(analyzer, tmp_path):
    """_cleanup gestisce directory inesistente senza errori."""
    target = tmp_path / "nonexistent" / "repo"
    # Should not raise
    analyzer._cleanup(target)


# ── Test Constructor ───────────────────────────────────────────────

def test_analyzer_constructor_defaults():
    """RepoAnalyzer ha default sensati."""
    a = RepoAnalyzer()
    assert a._clone_timeout == 120
    assert a._max_file_size == 512 * 1024
    assert "research_sandbox" in str(a._sandbox)


def test_analyzer_constructor_custom():
    """RepoAnalyzer accetta parametri custom."""
    a = RepoAnalyzer(
        sandbox_dir="/tmp/test_sandbox",
        clone_timeout_s=30,
        max_file_size_kb=128,
    )
    assert a._clone_timeout == 30
    assert a._max_file_size == 128 * 1024
    assert str(a._sandbox) == "/tmp/test_sandbox"
