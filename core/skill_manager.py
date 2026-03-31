"""Noxen - Dynamic Skill Manager.

Responsibilities:
  1. Scan /skills directory for Python files/packages
  2. Dynamically import and validate Skill subclasses
  3. Hot-reload on file change (via watchfiles)
  4. Provide a registry for the API and LLM layers
  5. Handle skill lifecycle (setup / teardown)

Design decisions:
  - Uses importlib for dynamic imports (no exec/eval)
  - Each skill file can contain multiple Skill subclasses
  - Skills from git repos: clone into /skills/<repo-name>/ and they auto-load
  - Thread-safe registry using asyncio locks
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Any

from .skill_base import Skill, SkillResult

logger = logging.getLogger("noxen.skills")


class SkillManager:
    """Discovers, loads, and manages Noxen skills."""

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self._registry: dict[str, Skill] = {}  # name -> instance
        self._modules: dict[str, Any] = {}      # module_name -> module
        self._lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────

    @property
    def skills(self) -> dict[str, Skill]:
        return dict(self._registry)

    @property
    def active_count(self) -> int:
        return len(self._registry)

    def get(self, name: str) -> Skill | None:
        return self._registry.get(name)

    async def execute_skill(self, skill_name: str, **kwargs: Any) -> SkillResult:
        """Execute a skill by name with given parameters."""
        skill = self._registry.get(skill_name)
        if not skill:
            return SkillResult(
                success=False,
                error=f"Skill '{skill_name}' not found. Available: {list(self._registry.keys())}",
            )
        try:
            return await skill.execute(**kwargs)
        except Exception as e:
            logger.exception(f"Skill '{skill_name}' execution failed")
            return SkillResult(success=False, error=str(e))

    async def run_pipeline(self, **kwargs: Any) -> dict[str, SkillResult]:
        """Execute all skills in priority order (1=first). Orchestrators can call sub-skills."""
        results: dict[str, SkillResult] = {}
        ordered = sorted(self._registry.values(), key=lambda s: s.metadata.priority)
        for skill in ordered:
            try:
                result = await skill.execute(**kwargs)
                results[skill.metadata.name] = result
            except Exception as e:
                logger.exception(f"Pipeline: skill '{skill.metadata.name}' failed")
                results[skill.metadata.name] = SkillResult(success=False, error=str(e))
        return results

    def get_by_priority(self) -> list[dict[str, Any]]:
        """Return skills sorted by priority with their metadata."""
        ordered = sorted(self._registry.values(), key=lambda s: s.metadata.priority)
        return [
            {
                "name": s.metadata.name,
                "priority": s.metadata.priority,
                "depends_on": s.metadata.depends_on,
                "category": s.metadata.category.value,
                "description": s.metadata.description,
            }
            for s in ordered
        ]

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Export all loaded skills as OpenAI-compatible tool definitions."""
        return [skill.to_tool_schema() for skill in self._registry.values()]

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def load_all(self) -> dict[str, str]:
        """Scan ricorsivo di skills_dir (supporta gerarchia gruppi). Returns {name: status}."""
        report: dict[str, str] = {}
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        targets = self._discover_skill_files(self.skills_dir)

        for filepath in sorted(targets):
            loaded = await self._load_file(filepath)
            for name, status in loaded.items():
                report[name] = status

        logger.info(f"Loaded {self.active_count} skills from {self.skills_dir}")
        return report

    def _discover_skill_files(self, root: Path, depth: int = 0) -> list[Path]:
        """Trova tutti i file skill ricorsivamente (max 3 livelli).

        Struttura supportata:
          skills/mia_skill.py              -> skill singola
          skills/gruppo/skill.py           -> skill in gruppo
          skills/gruppo/package/__init__.py -> package skill in gruppo
          skills/package/__init__.py       -> package skill root
        """
        if depth > 2:
            return []

        targets: list[Path] = []
        try:
            entries = sorted(root.iterdir())
        except PermissionError:
            return []

        for item in entries:
            if item.name.startswith("_") or item.name.startswith("."):
                continue

            if item.is_file() and item.suffix == ".py":
                targets.append(item)
            elif item.is_dir():
                init = item / "__init__.py"
                if init.exists():
                    # E' un package — carica __init__.py
                    targets.append(init)
                else:
                    # E' un gruppo/cartella — scan ricorsivo
                    targets.extend(self._discover_skill_files(item, depth + 1))

        return targets

    async def unload_all(self) -> None:
        """Teardown and remove all loaded skills."""
        async with self._lock:
            for name, skill in list(self._registry.items()):
                try:
                    await skill.teardown()
                except Exception:
                    logger.exception(f"Error tearing down skill '{name}'")
            self._registry.clear()
            self._modules.clear()

    async def reload_skill(self, name: str) -> str:
        """Reload a specific skill by name."""
        skill = self._registry.get(name)
        if not skill:
            return f"Skill '{name}' not found"

        # Find which module this skill came from
        mod_name = skill.__class__.__module__
        mod = self._modules.get(mod_name)
        if not mod:
            return f"Module for '{name}' not tracked"

        async with self._lock:
            # Teardown old instance
            try:
                await skill.teardown()
            except Exception:
                pass
            del self._registry[name]

            # Reload the module
            try:
                reloaded = importlib.reload(mod)
                self._modules[mod_name] = reloaded
                classes = self._extract_skill_classes(reloaded)
                for cls in classes:
                    instance = cls()
                    instance.hub = self
                    await instance.setup()
                    self._registry[instance.metadata.name] = instance
                return "reloaded"
            except Exception as e:
                logger.exception(f"Failed to reload '{name}'")
                return f"error: {e}"

    # ── Internal ──────────────────────────────────────────────────────

    async def _load_file(self, filepath: Path) -> dict[str, str]:
        """Import a single file and register all Skill subclasses found."""
        results: dict[str, str] = {}
        module_name = f"noxen_skills.{filepath.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if not spec or not spec.loader:
                results[str(filepath)] = "invalid module spec"
                return results

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self._modules[module_name] = module

        except Exception as e:
            logger.warning(f"Failed to import {filepath}: {e}")
            results[str(filepath)] = f"import_error: {e}"
            return results

        classes = self._extract_skill_classes(module)
        if not classes:
            results[str(filepath)] = "no_skills_found"
            return results

        async with self._lock:
            for cls in classes:
                try:
                    instance = cls()
                    instance.hub = self  # Inject manager so skill can call other skills
                    await instance.setup()
                    self._registry[instance.metadata.name] = instance
                    results[instance.metadata.name] = "loaded"
                    logger.info(f"  ✓ {instance.metadata.name} v{instance.metadata.version} [P{instance.metadata.priority}]")
                except Exception as e:
                    results[cls.__name__] = f"init_error: {e}"
                    logger.warning(f"  ✗ {cls.__name__}: {e}")

        return results

    @staticmethod
    def _extract_skill_classes(module: Any) -> list[type[Skill]]:
        """Find all concrete Skill subclasses in a module."""
        classes: list[type[Skill]] = []
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Skill)
                and obj is not Skill
                and not inspect.isabstract(obj)
                and getattr(obj, "metadata", None) is not None
            ):
                classes.append(obj)
        return classes
