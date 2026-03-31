"""Noxen - Sandbox Manager for Execution Engine.

Gestisce l'isolamento dell'esecuzione:
  - Copia il progetto in sandbox_dir
  - Crea branch git dedicato (noxen/run-{timestamp})
  - Sanitizza file .env (rimuove valori sensibili)
  - Persiste info sandbox su Qdrant collection "cycles"
  - Cleanup automatico dopo esecuzione

Step 4.1 della Phase 4.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("noxen.sandbox")


# ── Dataclass ────────────────────────────────────────────────────────

@dataclass
class SandboxInfo:
    """Informazioni su una sandbox creata."""

    sandbox_id: str
    source_path: str
    sandbox_path: str
    branch_name: str
    created_at: str
    status: str = "active"  # active, completed, failed, cleaned
    sanitized_files: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Constants ────────────────────────────────────────────────────────

# File/directory patterns da NON copiare nella sandbox
EXCLUDE_PATTERNS: set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".next",
    ".nuxt",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    "coverage",
    ".coverage",
}

# Pattern per file con segreti da sanitizzare
ENV_FILE_PATTERNS: set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.development",
}

# Regex per chiavi sensibili dentro file env
SENSITIVE_KEY_PATTERN = re.compile(
    r"^(\s*(?:export\s+)?)"                       # optional export prefix
    r"("
    r"[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL|AUTH)"
    r"[A-Z_]*"
    r")"
    r"(\s*=\s*)"                                    # =
    r"(.+)$",                                       # value
    re.IGNORECASE | re.MULTILINE,
)


# ── SandboxManager ──────────────────────────────────────────────────

class SandboxManager:
    """Gestisce sandbox isolate per l'Execution Engine.

    Crea copie del progetto in una directory dedicata, con branch git
    separato e file .env sanitizzati.
    """

    def __init__(
        self,
        sandbox_base_dir: str = "./data/execution_sandbox",
        qdrant_persist: bool = True,
    ) -> None:
        self._base_dir = Path(sandbox_base_dir)
        self._qdrant_persist = qdrant_persist
        self._active_sandboxes: dict[str, SandboxInfo] = {}

    async def create(
        self,
        project_path: str,
        run_id: str | None = None,
    ) -> SandboxInfo:
        """Crea una sandbox isolata per un progetto.

        1. Copia il progetto (esclude node_modules, .venv, etc.)
        2. Inizializza git e crea branch dedicato
        3. Sanitizza file .env
        4. Persiste info su Qdrant

        Args:
            project_path: Path assoluto del progetto sorgente.
            run_id: ID opzionale della run. Se None, generato automaticamente.

        Returns:
            SandboxInfo con tutti i dettagli della sandbox.

        Raises:
            FileNotFoundError: Se project_path non esiste.
            RuntimeError: Se la copia o git init fallisce.
        """
        source = Path(project_path).resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Project path not found: {project_path}")

        sandbox_id = run_id or uuid.uuid4().hex[:12]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        branch_name = f"noxen/run-{timestamp}-{sandbox_id[:6]}"

        # Create sandbox directory
        self._base_dir.mkdir(parents=True, exist_ok=True)
        sandbox_path = self._base_dir / f"sandbox-{sandbox_id}"

        info = SandboxInfo(
            sandbox_id=sandbox_id,
            source_path=str(source),
            sandbox_path=str(sandbox_path),
            branch_name=branch_name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # Step 1: Copy project
            logger.info(
                "sandbox.creating",
                sandbox_id=sandbox_id,
                source=str(source),
                target=str(sandbox_path),
            )
            await self._copy_project(source, sandbox_path)

            # Step 2: Git init + branch
            await self._setup_git(sandbox_path, branch_name)

            # Step 3: Sanitize env files
            sanitized = self._sanitize_env_files(sandbox_path)
            info.sanitized_files = sanitized

            # Step 4: Persist to Qdrant
            if self._qdrant_persist:
                await self._persist_sandbox_info(info)

            self._active_sandboxes[sandbox_id] = info
            logger.info(
                "sandbox.created",
                sandbox_id=sandbox_id,
                branch=branch_name,
                sanitized_count=len(sanitized),
            )

        except Exception as e:
            info.status = "failed"
            info.error = str(e)
            # Cleanup on failure
            if sandbox_path.exists():
                shutil.rmtree(sandbox_path, ignore_errors=True)
            logger.error("sandbox.create_failed", error=str(e))
            raise RuntimeError(f"Sandbox creation failed: {e}") from e

        return info

    async def cleanup(self, sandbox_id: str) -> bool:
        """Rimuovi una sandbox.

        Args:
            sandbox_id: ID della sandbox da rimuovere.

        Returns:
            True se rimossa, False se non trovata.
        """
        info = self._active_sandboxes.get(sandbox_id)
        if not info:
            return False

        sandbox_path = Path(info.sandbox_path)
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path, ignore_errors=True)
            logger.info("sandbox.cleaned", sandbox_id=sandbox_id)

        info.status = "cleaned"
        if self._qdrant_persist:
            await self._persist_sandbox_info(info)

        del self._active_sandboxes[sandbox_id]
        return True

    async def cleanup_all(self) -> int:
        """Rimuovi tutte le sandbox attive. Ritorna il count."""
        ids = list(self._active_sandboxes.keys())
        count = 0
        for sid in ids:
            if await self.cleanup(sid):
                count += 1
        return count

    def get_sandbox(self, sandbox_id: str) -> SandboxInfo | None:
        """Ritorna info sulla sandbox, o None."""
        return self._active_sandboxes.get(sandbox_id)

    def list_sandboxes(self) -> list[SandboxInfo]:
        """Lista tutte le sandbox attive."""
        return list(self._active_sandboxes.values())

    # ── Internal methods ─────────────────────────────────────────────

    async def _copy_project(self, source: Path, target: Path) -> None:
        """Copia il progetto escludendo directory pesanti/non necessarie."""

        def _do_copy():
            def _ignore(directory: str, contents: list[str]) -> set[str]:
                ignored = set()
                dir_path = Path(directory)
                for item in contents:
                    if item in EXCLUDE_PATTERNS:
                        # Only exclude if it's actually a directory
                        item_path = dir_path / item
                        if item_path.is_dir():
                            ignored.add(item)
                return ignored

            shutil.copytree(
                source,
                target,
                ignore=_ignore,
                dirs_exist_ok=False,
            )

        # Run in executor to not block event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_copy)

    async def _setup_git(self, sandbox_path: Path, branch_name: str) -> None:
        """Inizializza git (se non presente) e crea branch dedicato."""
        git_dir = sandbox_path / ".git"

        if not git_dir.exists():
            # git init
            await self._run_git(sandbox_path, "init")
            # Initial commit
            await self._run_git(sandbox_path, "add", "-A")
            await self._run_git(
                sandbox_path, "commit", "-m", "Noxen sandbox init",
                "--allow-empty",
            )

        # Create and checkout branch
        await self._run_git(sandbox_path, "checkout", "-b", branch_name)

    async def _run_git(self, cwd: Path, *args: str) -> str:
        """Esegui un comando git e ritorna stdout."""
        cmd = ["git"] + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            # git commit --allow-empty may have non-zero on empty repo warnings
            if "nothing to commit" not in error_msg:
                raise RuntimeError(
                    f"git {' '.join(args)} failed (rc={proc.returncode}): {error_msg}"
                )

        return stdout.decode("utf-8", errors="replace").strip()

    def _sanitize_env_files(self, sandbox_path: Path) -> list[str]:
        """Sanitizza file .env nella sandbox. Ritorna lista file sanitizzati."""
        sanitized = []

        for root, _dirs, files in os.walk(sandbox_path):
            for fname in files:
                if fname in ENV_FILE_PATTERNS:
                    fpath = Path(root) / fname
                    rel_path = str(fpath.relative_to(sandbox_path))
                    if self._sanitize_single_env(fpath):
                        sanitized.append(rel_path)

        return sanitized

    def _sanitize_single_env(self, env_path: Path) -> bool:
        """Sanitizza un singolo file .env. Ritorna True se modificato."""
        try:
            content = env_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return False

        original = content

        def _redact(match: re.Match) -> str:
            prefix = match.group(1)    # optional export
            key = match.group(2)       # KEY_NAME
            equals = match.group(3)    # =
            return f"{prefix}{key}{equals}REDACTED_BY_NEURAL_HUB"

        content = SENSITIVE_KEY_PATTERN.sub(_redact, content)

        if content != original:
            env_path.write_text(content, encoding="utf-8")
            return True
        return False

    async def _persist_sandbox_info(self, info: SandboxInfo) -> None:
        """Persiste info sandbox su Qdrant collection 'cycles'."""
        try:
            from core.qdrant_client import NoxenQdrantClient

            client = NoxenQdrantClient.get_instance()
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.upsert_payload(
                    collection="cycles",
                    point_id=info.sandbox_id,
                    payload={
                        "type": "sandbox",
                        **info.to_dict(),
                    },
                ),
            )
        except Exception as e:
            # Non-fatal: sandbox funziona anche senza Qdrant
            logger.warning(
                "sandbox.qdrant_persist_failed",
                error=str(e),
            )
