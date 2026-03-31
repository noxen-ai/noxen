"""Noxen - Repo Cloner & Analyzer for Research Agent.

Clona repo GitHub in sandbox, analizza struttura con tree-sitter AST,
estrae funzioni, classi, import, endpoint API.
Cleanup automatico dopo analisi.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger
from core.research.treesitter_parser import TreeSitterParser

logger = get_logger("noxen.repo_analyzer")


# ── Constants ────────────────────────────────────────────────────────

LANG_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".swift": "Swift",
    ".kt": "Kotlin",
}

SKIP_DIRS: set[str] = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "vendor", "target",
    ".idea", ".vscode", "coverage", ".coverage",
}

IMPORTANT_FILENAMES: set[str] = {
    "README.md", "README.rst", "README.txt", "README",
    "setup.py", "setup.cfg", "pyproject.toml",
    "package.json", "go.mod", "Cargo.toml", "pom.xml",
    "Makefile", "Dockerfile", "docker-compose.yml",
    "requirements.txt", "Pipfile", "poetry.lock",
    ".env.example", "config.yaml", "config.yml",
}

FRAMEWORK_PATTERNS: dict[str, list[str]] = {
    "fastapi": [r"from\s+fastapi", r"@app\.(get|post|put|delete|patch)"],
    "flask": [r"from\s+flask", r"@app\.route"],
    "django": [r"from\s+django", r"urlpatterns"],
    "express": [r"require\(['\"]express['\"]\)", r"app\.(get|post|put|delete)"],
    "gin": [r"\"github\.com/gin-gonic/gin\"", r"gin\.Default\(\)"],
    "spring": [r"@RestController", r"@RequestMapping"],
    "react": [r"from\s+['\"]react['\"]", r"import\s+React"],
    "vue": [r"from\s+['\"]vue['\"]", r"createApp"],
    "angular": [r"@Component", r"@NgModule"],
}

# Map display language names back to tree-sitter names
_DISPLAY_TO_TS_LANG: dict[str, str] = {
    "Python": "python",
    "JavaScript": "javascript",
    "TypeScript": "typescript",
    "Go": "go",
    "Java": "java",
}


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class FunctionInfo:
    """Informazioni su una funzione/metodo estratta."""
    name: str
    file_path: str
    language: str
    line_number: int
    is_async: bool = False
    decorators: list[str] = field(default_factory=list)
    docstring: str = ""


@dataclass
class ClassInfo:
    """Informazioni su una classe estratta."""
    name: str
    file_path: str
    language: str
    line_number: int
    bases: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    docstring: str = ""


@dataclass
class ImportInfo:
    """Informazioni su un import estratto."""
    module: str
    file_path: str
    language: str
    line_number: int
    alias: str = ""


@dataclass
class RepoAnalysis:
    """Risultato completo dell'analisi di un repo."""
    repo_url: str
    languages: dict[str, int] = field(default_factory=dict)  # lang -> file count
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    endpoints: list[dict[str, str]] = field(default_factory=list)
    file_count: int = 0
    total_lines: int = 0
    important_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Analyzer ─────────────────────────────────────────────────────────

class RepoAnalyzer:
    """Clona e analizza repo GitHub con tree-sitter AST.

    Flusso: clone -> analyze -> cleanup.
    Supporta: Python, JS/TS, Go, Java (via tree-sitter).
    """

    def __init__(
        self,
        sandbox_dir: str = "./data/research_sandbox",
        clone_timeout_s: int = 120,
        max_file_size_kb: int = 512,
        parser: TreeSitterParser | None = None,
    ) -> None:
        self._sandbox = Path(sandbox_dir)
        self._clone_timeout = clone_timeout_s
        self._max_file_size = max_file_size_kb * 1024  # bytes
        self._logger = get_logger("repo_analyzer")
        self._parser = parser or TreeSitterParser()

    async def clone_and_analyze(
        self,
        repo_url: str,
        depth: int = 1,
    ) -> RepoAnalysis:
        """Clona repo, analizza, e cleanup.

        Args:
            repo_url: URL GitHub (https://github.com/owner/repo)
            depth: Profondita' del clone (default: shallow clone depth=1)

        Returns:
            RepoAnalysis con tutti i dati estratti.
        """
        analysis = RepoAnalysis(repo_url=repo_url)
        clone_path: Path | None = None

        try:
            clone_path = await self._clone(repo_url, depth)
            analysis = await self._analyze(clone_path, repo_url)
        except asyncio.TimeoutError:
            analysis.errors.append(f"Clone timeout after {self._clone_timeout}s")
            self._logger.error(f"Clone timeout for {repo_url}")
        except Exception as e:
            analysis.errors.append(str(e))
            self._logger.error(f"Analysis failed for {repo_url}: {e}")
        finally:
            if clone_path and clone_path.exists():
                self._cleanup(clone_path)

        return analysis

    async def _clone(
        self,
        repo_url: str,
        depth: int = 1,
    ) -> Path:
        """Clone repo in sandbox con timeout.

        Usa git subprocess per shallow clone.
        """
        self._sandbox.mkdir(parents=True, exist_ok=True)
        clone_dir = Path(tempfile.mkdtemp(dir=self._sandbox))

        cmd = [
            "git", "clone",
            "--depth", str(depth),
            "--single-branch",
            repo_url,
            str(clone_dir / "repo"),
        ]

        self._logger.info(f"Cloning {repo_url} (depth={depth})")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._clone_timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            self._cleanup(clone_dir)
            raise

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            self._cleanup(clone_dir)
            raise RuntimeError(f"git clone failed (rc={proc.returncode}): {error_msg}")

        repo_path = clone_dir / "repo"
        if not repo_path.exists():
            self._cleanup(clone_dir)
            raise RuntimeError(f"Clone directory not found: {repo_path}")

        return repo_path

    async def _analyze(self, path: Path, repo_url: str) -> RepoAnalysis:
        """Analizza un repo clonato.

        Walks the file tree, usa tree-sitter per AST parsing.
        """
        analysis = RepoAnalysis(repo_url=repo_url)

        for root, dirs, files in os.walk(path):
            # Skip directory non interessanti
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            for fname in files:
                fpath = Path(root) / fname
                rel_path = str(fpath.relative_to(path))

                # Track important files
                if fname in IMPORTANT_FILENAMES:
                    analysis.important_files.append(rel_path)

                # Detect language (display name)
                lang = self._detect_language(fpath)
                if not lang:
                    continue

                # Skip files troppo grandi
                try:
                    if fpath.stat().st_size > self._max_file_size:
                        continue
                except OSError:
                    continue

                analysis.languages[lang] = analysis.languages.get(lang, 0) + 1
                analysis.file_count += 1

                # Read & analyze
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    lines = content.count("\n") + 1
                    analysis.total_lines += lines

                    # Tree-sitter AST parsing
                    self._analyze_with_treesitter(
                        fpath, content, rel_path, lang, analysis
                    )

                    # Framework detection (still regex — text pattern matching)
                    self._detect_frameworks(content, analysis)

                    # Endpoint extraction (still regex — decorator/route patterns)
                    self._extract_endpoints(content, rel_path, lang, analysis)

                except Exception as e:
                    analysis.errors.append(f"Error analyzing {rel_path}: {e}")

        return analysis

    def _analyze_with_treesitter(
        self,
        fpath: Path,
        content: str,
        rel_path: str,
        display_lang: str,
        analysis: RepoAnalysis,
    ) -> None:
        """Analizza un file con tree-sitter e popola l'analysis."""
        parsed = self._parser.parse_file(fpath, content)
        if not parsed:
            return

        # Convert ParsedFunction -> FunctionInfo
        for pf in parsed.functions:
            analysis.functions.append(FunctionInfo(
                name=pf.name,
                file_path=rel_path,
                language=display_lang,
                line_number=pf.start_line,
                is_async=pf.is_async,
                decorators=pf.decorators,
                docstring=pf.docstring or "",
            ))

        # Convert ParsedClass -> ClassInfo
        for pc in parsed.classes:
            analysis.classes.append(ClassInfo(
                name=pc.name,
                file_path=rel_path,
                language=display_lang,
                line_number=pc.start_line,
                bases=pc.base_classes,
                methods=pc.methods,
                docstring=pc.docstring or "",
            ))

        # Convert ParsedImport -> ImportInfo
        for pi in parsed.imports:
            analysis.imports.append(ImportInfo(
                module=pi.module,
                file_path=rel_path,
                language=display_lang,
                line_number=pi.line,
                alias=pi.alias or "",
            ))

    def _detect_language(self, file_path: Path) -> str:
        """Detecta linguaggio dal suffisso del file."""
        return LANG_EXTENSIONS.get(file_path.suffix.lower(), "")

    def _detect_frameworks(self, content: str, analysis: RepoAnalysis) -> None:
        """Detecta framework usati nel file (regex — text pattern match)."""
        for framework, patterns in FRAMEWORK_PATTERNS.items():
            if framework in analysis.frameworks:
                continue
            for pat in patterns:
                if re.search(pat, content):
                    analysis.frameworks.append(framework)
                    break

    def _extract_endpoints(
        self, content: str, rel_path: str, lang: str, analysis: RepoAnalysis
    ) -> None:
        """Estrai API endpoints dal codice (regex — route pattern match)."""
        endpoint_patterns = [
            # FastAPI / Flask
            (r'@\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', "method_route"),
            # Express.js
            (r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', "method_route"),
            # Django urls
            (r'path\s*\(\s*["\']([^"\']+)["\']', "django_path"),
            # Go gin/mux
            (r'\.(GET|POST|PUT|DELETE|PATCH)\s*\(\s*"([^"]+)"', "method_route"),
            # Spring
            (r'@(Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']', "method_route"),
        ]

        for pattern, ptype in endpoint_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                if ptype == "method_route":
                    method = match.group(1).upper()
                    path = match.group(2)
                elif ptype == "django_path":
                    method = "ANY"
                    path = match.group(1)
                else:
                    continue

                analysis.endpoints.append({
                    "method": method,
                    "path": path,
                    "file": rel_path,
                    "language": lang,
                })

    def _cleanup(self, path: Path) -> None:
        """Rimuovi directory clonata."""
        try:
            # Risali al parent tmpdir se siamo dentro /repo
            cleanup_target = path
            if path.name == "repo" and path.parent.exists():
                cleanup_target = path.parent

            shutil.rmtree(cleanup_target, ignore_errors=True)
            self._logger.info(f"Cleaned up {cleanup_target}")
        except Exception as e:
            self._logger.warning(f"Cleanup failed for {path}: {e}")
