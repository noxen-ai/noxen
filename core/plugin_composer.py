"""Noxen - Plugin Composer.

Composes a new Claude Code plugin from installed skill repositories.
Uses the priority/hierarchy to determine skill ordering and orchestration.

Output: a .claude-plugin/ directory ready for use with Claude Code.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from config import settings
from .claude_skill_parser import ClaudePlugin, ClaudeSkill, parse_plugin_repo

logger = logging.getLogger("noxen.composer")

OUTPUT_DIR = settings.data_dir / "composed_plugins"


class PluginComposer:
    """Manages Claude Code plugins and composes new ones."""

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self._plugins: dict[str, ClaudePlugin] = {}

    @property
    def plugins(self) -> dict[str, ClaudePlugin]:
        return dict(self._plugins)

    def scan_all(self) -> dict[str, ClaudePlugin]:
        """Scan skills_dir for all Claude Code plugin repos.

        Handles both flat repos (repo/.claude-plugin/) and nested repos
        (repo/sub-skill/.claude-plugin/) like laravel/agent-skills.
        """
        self._plugins.clear()

        if not self.skills_dir.exists():
            return {}

        for item in sorted(self.skills_dir.iterdir()):
            if item.name.startswith(("_", ".")) or not item.is_dir():
                continue

            # Check if this repo itself is a plugin
            if self._is_plugin_dir(item):
                plugin = parse_plugin_repo(item)
                if plugin and (plugin.skills or plugin.commands or plugin.agents):
                    self._plugins[plugin.name] = plugin
                continue

            # Check subdirectories (nested plugin repos like laravel/agent-skills)
            has_sub_plugins = False
            for sub in sorted(item.iterdir()):
                if sub.name.startswith(("_", ".")) or not sub.is_dir():
                    continue
                if self._is_plugin_dir(sub):
                    plugin = parse_plugin_repo(sub, repo_name=f"{item.name}/{sub.name}")
                    if plugin:
                        self._plugins[plugin.name] = plugin
                        has_sub_plugins = True

            # If no sub-plugins found, try scanning the whole repo for SKILL.md files
            if not has_sub_plugins and any(item.rglob("SKILL.md")):
                plugin = parse_plugin_repo(item)
                if plugin and (plugin.skills or plugin.commands or plugin.agents):
                    self._plugins[plugin.name] = plugin

        logger.info(f"Scanned {len(self._plugins)} Claude Code plugins")
        return dict(self._plugins)

    @staticmethod
    def _is_plugin_dir(path: Path) -> bool:
        """Check if a directory is a Claude Code plugin."""
        return (
            (path / ".claude-plugin").exists()
            or (path / "CLAUDE.md").exists()
            or (path / "SKILL.md").exists()
        )

    def get_all_skills(self) -> list[dict[str, Any]]:
        """Return a flat list of all skills across all plugins."""
        all_skills: list[dict[str, Any]] = []
        for plugin in self._plugins.values():
            for skill in plugin.skills:
                all_skills.append({
                    "name": skill.name,
                    "description": skill.description,
                    "version": skill.version,
                    "author": skill.author,
                    "tags": skill.tags,
                    "dependencies": skill.dependencies,
                    "path": skill.path,
                    "plugin": plugin.name,
                    "group": skill.plugin_group,
                    "type": skill.skill_type,
                })
            for cmd in plugin.commands:
                all_skills.append({
                    "name": cmd.name,
                    "description": cmd.description,
                    "plugin": plugin.name,
                    "path": cmd.path,
                    "type": "command",
                })
            for agent in plugin.agents:
                all_skills.append({
                    "name": agent.name,
                    "description": agent.description,
                    "plugin": plugin.name,
                    "path": agent.path,
                    "type": "agent",
                })
        return all_skills

    def get_plugin_summary(self) -> list[dict[str, Any]]:
        """Return summary of all parsed plugins."""
        return [
            {
                "name": p.name,
                "description": p.description,
                "version": p.version,
                "owner": p.owner,
                "source_repo": p.source_repo,
                "skill_count": len(p.skills),
                "command_count": len(p.commands),
                "agent_count": len(p.agents),
            }
            for p in self._plugins.values()
        ]

    def compose_plugin(
        self,
        name: str,
        description: str,
        selected_skills: list[dict[str, str]],
        owner_name: str = "Noxen",
        version: str = "1.0.0",
    ) -> Path:
        """Compose a new Claude Code plugin from selected skills.

        Args:
            name: Plugin name
            description: Plugin description
            selected_skills: List of {"plugin": ..., "skill": ..., "priority": ...}
            owner_name: Author name
            version: Plugin version

        Returns:
            Path to the composed plugin directory
        """
        output = OUTPUT_DIR / name
        plugin_dir = output / ".claude-plugin"

        # Clean previous
        if output.exists():
            shutil.rmtree(output)

        plugin_dir.mkdir(parents=True, exist_ok=True)

        # Sort by priority
        sorted_skills = sorted(selected_skills, key=lambda s: int(s.get("priority", 3)))

        # Build plugin groups from selected skills
        plugin_entries: list[dict[str, Any]] = []
        skills_copied: list[str] = []

        for sel in sorted_skills:
            source_plugin = self._plugins.get(sel["plugin"])
            if not source_plugin:
                continue

            # Find the skill in the source plugin
            skill = None
            for s in source_plugin.skills:
                if s.name == sel["skill"]:
                    skill = s
                    break
            if not skill:
                for s in source_plugin.commands + source_plugin.agents:
                    if s.name == sel["skill"]:
                        skill = s
                        break
            if not skill:
                continue

            # Copy skill directory to output
            source_dir = self.skills_dir / source_plugin.source_repo / skill.path
            if source_dir.is_dir():
                dest = output / skill.path
                shutil.copytree(source_dir, dest, dirs_exist_ok=True)
                skills_copied.append(f"./{skill.path}")

                plugin_entries.append({
                    "name": skill.plugin_group or skill.name,
                    "description": skill.description,
                    "source": "./",
                    "strict": False,
                    "skills": [f"./{skill.path}"],
                })

        # Copy commands and agents from selected plugins
        for sel in sorted_skills:
            source_plugin = self._plugins.get(sel["plugin"])
            if not source_plugin:
                continue

            # Copy commands
            src_cmds = self.skills_dir / source_plugin.source_repo / ".claude-plugin" / "commands"
            if src_cmds.is_dir():
                dest_cmds = plugin_dir / "commands"
                dest_cmds.mkdir(exist_ok=True)
                for cmd_file in src_cmds.glob("*.md"):
                    dest_file = dest_cmds / cmd_file.name
                    if not dest_file.exists():
                        shutil.copy2(cmd_file, dest_file)

            # Copy agents
            src_agents = self.skills_dir / source_plugin.source_repo / ".claude-plugin" / "agents"
            if src_agents.is_dir():
                dest_agents = plugin_dir / "agents"
                dest_agents.mkdir(exist_ok=True)
                for agent_file in src_agents.glob("*.md"):
                    dest_file = dest_agents / agent_file.name
                    if not dest_file.exists():
                        shutil.copy2(agent_file, dest_file)

        # Generate plugin.json
        manifest = {
            "name": name,
            "owner": {"name": owner_name},
            "metadata": {
                "description": description,
                "version": version,
            },
            "plugins": plugin_entries,
        }

        (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2))

        # Generate marketplace.json
        marketplace = {
            "name": name,
            "version": version,
            "description": description,
            "author": {"name": owner_name},
            "keywords": ["noxen", "composed-plugin"],
        }
        (plugin_dir / "marketplace.json").write_text(json.dumps(marketplace, indent=2))

        logger.info(
            f"Composed plugin '{name}' with {len(skills_copied)} skills -> {output}"
        )
        return output
