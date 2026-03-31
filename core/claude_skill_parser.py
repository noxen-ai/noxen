"""Noxen - Claude Code Skill Parser.

Parses Claude Code plugin repositories:
  - Reads .claude-plugin/plugin.json for plugin structure
  - Reads SKILL.md / CLAUDE.md frontmatter for skill metadata
  - Builds a unified registry of Claude Code skills

Supported structures:
  repo/.claude-plugin/plugin.json   -> plugin manifest with skill list
  repo/01-topic/skill-name/SKILL.md -> individual skill with YAML frontmatter
  repo/.claude-plugin/commands/*.md -> slash commands
  repo/.claude-plugin/agents/*.md   -> agent definitions
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("noxen.claude_parser")


@dataclass
class ClaudeSkill:
    """A single Claude Code skill (parsed from SKILL.md or plugin.json)."""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = "unknown"
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    path: str = ""            # Relative path to skill directory
    source_repo: str = ""     # Which installed repo this comes from
    plugin_group: str = ""    # Plugin group from plugin.json
    content_file: str = ""    # Path to SKILL.md or CLAUDE.md
    skill_type: str = "skill" # skill, command, agent


@dataclass
class ClaudePlugin:
    """A Claude Code plugin (parsed from plugin.json)."""
    name: str
    description: str
    version: str = "1.0.0"
    owner: str = "unknown"
    source_repo: str = ""
    skills: list[ClaudeSkill] = field(default_factory=list)
    commands: list[ClaudeSkill] = field(default_factory=list)
    agents: list[ClaudeSkill] = field(default_factory=list)
    raw_manifest: dict[str, Any] = field(default_factory=dict)


def _parse_yaml_frontmatter(filepath: Path) -> dict[str, Any]:
    """Extract YAML frontmatter from a markdown file."""
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}

    frontmatter: dict[str, Any] = {}
    for line in m.group(1).split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            # Parse YAML-like lists [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                items = [x.strip().strip("\"'") for x in val[1:-1].split(",")]
                frontmatter[key] = [x for x in items if x]
            elif val.lower() in ("true", "false"):
                frontmatter[key] = val.lower() == "true"
            else:
                frontmatter[key] = val.strip("\"'")

    return frontmatter


def _extract_owner(manifest: dict[str, Any]) -> str:
    """Extract owner/author name from various manifest formats."""
    for key in ["owner", "author"]:
        val = manifest.get(key)
        if isinstance(val, dict):
            return val.get("name", "unknown")
        if isinstance(val, str) and val:
            return val
    return "unknown"


def parse_plugin_repo(repo_dir: Path, repo_name: str = "", _depth: int = 0) -> ClaudePlugin | None:
    """Parse a Claude Code plugin repository.

    Looks for:
      1. .claude-plugin/plugin.json — main manifest
      2. .claude-plugin/marketplace.json — alternate manifest
      3. Fallback: scan for SKILL.md files recursively
    """
    if _depth > 2:
        return None

    if not repo_name:
        repo_name = repo_dir.name

    plugin_dir = repo_dir / ".claude-plugin"
    manifest_path = plugin_dir / "plugin.json"
    marketplace_path = plugin_dir / "marketplace.json"

    # Try plugin.json first, then marketplace.json
    manifest: dict[str, Any] = {}
    for mpath in [manifest_path, marketplace_path]:
        if mpath.exists():
            try:
                manifest = json.loads(mpath.read_text())
                break
            except Exception as e:
                logger.warning(f"Failed to parse {mpath}: {e}")

    if not manifest:
        # Fallback: scan for SKILL.md files
        return _scan_skill_files(repo_dir, repo_name)

    # Parse manifest
    plugin = ClaudePlugin(
        name=manifest.get("name", repo_name),
        description=manifest.get("metadata", {}).get("description", "")
            or manifest.get("description", ""),
        version=manifest.get("metadata", {}).get("version", "")
            or manifest.get("version", "1.0.0"),
        owner=_extract_owner(manifest),
        source_repo=repo_name,
        raw_manifest=manifest,
    )

    # Parse plugin groups and skills
    for plugin_entry in manifest.get("plugins", []):
        group_name = plugin_entry.get("name", "")
        group_desc = plugin_entry.get("description", "")

        # Handle "source" field (points to sub-plugin directory)
        # Skip self-references like "./" and only follow if no "skills" list
        source = plugin_entry.get("source", "")
        if isinstance(source, dict):
            source = source.get("path", source.get("url", ""))
        if not isinstance(source, str):
            source = ""
        has_skill_paths = bool(plugin_entry.get("skills", []))
        if source and not has_skill_paths:
            source_path = source.removeprefix("./")
            sub_dir = repo_dir / source_path if source_path else None
            if sub_dir and sub_dir.is_dir() and sub_dir != repo_dir:
                sub_plugin = parse_plugin_repo(sub_dir, repo_name=f"{repo_name}/{group_name}", _depth=_depth + 1)
                if sub_plugin:
                    plugin.skills.extend(sub_plugin.skills)
                    plugin.commands.extend(sub_plugin.commands)
                    plugin.agents.extend(sub_plugin.agents)
                    # If sub-plugin had no skills/agents, register it as a skill entry
                    if not sub_plugin.skills and not sub_plugin.commands and not sub_plugin.agents:
                        plugin.skills.append(ClaudeSkill(
                            name=group_name,
                            description=group_desc or sub_plugin.description,
                            version=plugin_entry.get("version", "1.0.0"),
                            author=plugin_entry.get("author", {}).get("name", "unknown")
                                if isinstance(plugin_entry.get("author"), dict) else "unknown",
                            path=source_path,
                            source_repo=repo_name,
                            plugin_group=group_name,
                        ))
                continue

        # Handle "skills" field (list of skill directory paths)
        skill_paths = plugin_entry.get("skills", [])
        for spath in skill_paths:
            # Normalize path (remove ./ prefix)
            spath = spath.removeprefix("./")
            skill_dir = repo_dir / spath

            skill = _parse_skill_dir(skill_dir, repo_name, group_name)
            if skill:
                if not skill.description:
                    skill.description = group_desc
                plugin.skills.append(skill)

    # If manifest had no plugin entries, scan repo/skills/ directory
    if not manifest.get("plugins") and not plugin.skills:
        for skills_dir in [repo_dir / "skills"]:
            if skills_dir.is_dir():
                for skill_sub in sorted(skills_dir.iterdir()):
                    if skill_sub.is_dir() and not skill_sub.name.startswith(("_", ".")):
                        skill = _parse_skill_dir(skill_sub, repo_name)
                        if skill:
                            plugin.skills.append(skill)

    # Parse commands (check both .claude-plugin/commands/ and commands/)
    for commands_dir in [plugin_dir / "commands", repo_dir / "commands"]:
        if commands_dir.is_dir():
            for cmd_file in sorted(commands_dir.glob("*.md")):
                fm = _parse_yaml_frontmatter(cmd_file)
                plugin.commands.append(ClaudeSkill(
                    name=fm.get("name", cmd_file.stem),
                    description=fm.get("description", f"Command: {cmd_file.stem}"),
                    path=str(cmd_file.relative_to(repo_dir)),
                    source_repo=repo_name,
                    content_file=str(cmd_file),
                    skill_type="command",
                ))
            break  # use first found

    # Parse agents (check both .claude-plugin/agents/ and agents/)
    for agents_dir in [plugin_dir / "agents", repo_dir / "agents"]:
        if agents_dir.is_dir():
            for agent_file in sorted(agents_dir.glob("*.md")):
                fm = _parse_yaml_frontmatter(agent_file)
                plugin.agents.append(ClaudeSkill(
                    name=fm.get("name", agent_file.stem),
                    description=fm.get("description", f"Agent: {agent_file.stem}"),
                    path=str(agent_file.relative_to(repo_dir)),
                    source_repo=repo_name,
                    content_file=str(agent_file),
                    skill_type="agent",
                ))
            break  # use first found

    logger.info(
        f"Parsed plugin '{plugin.name}': "
        f"{len(plugin.skills)} skills, "
        f"{len(plugin.commands)} commands, "
        f"{len(plugin.agents)} agents"
    )
    return plugin


def _parse_skill_dir(skill_dir: Path, repo_name: str, group: str = "") -> ClaudeSkill | None:
    """Parse a single skill directory (looks for SKILL.md or CLAUDE.md)."""
    if not skill_dir.is_dir():
        return None

    # Find the skill definition file
    skill_file = None
    for candidate in ["SKILL.md", "CLAUDE.md", "README.md"]:
        f = skill_dir / candidate
        if f.exists():
            skill_file = f
            break

    if not skill_file:
        # No markdown found, still register the directory
        return ClaudeSkill(
            name=skill_dir.name,
            description=f"Skill: {skill_dir.name}",
            path=str(skill_dir.parent.name + "/" + skill_dir.name),
            source_repo=repo_name,
            plugin_group=group,
        )

    fm = _parse_yaml_frontmatter(skill_file)

    return ClaudeSkill(
        name=fm.get("name", skill_dir.name),
        description=fm.get("description", f"Skill: {skill_dir.name}"),
        version=fm.get("version", "1.0.0"),
        author=fm.get("author", "unknown"),
        tags=fm.get("tags", []),
        dependencies=fm.get("dependencies", []),
        path=str(skill_dir.parent.name + "/" + skill_dir.name),
        source_repo=repo_name,
        plugin_group=group,
        content_file=str(skill_file),
    )


def _scan_skill_files(repo_dir: Path, repo_name: str) -> ClaudePlugin:
    """Fallback: scan for SKILL.md/CLAUDE.md/commands/agents (max 4 levels deep)."""
    plugin = ClaudePlugin(
        name=repo_name,
        description=f"Skills from {repo_name}",
        source_repo=repo_name,
    )

    seen_dirs: set[str] = set()

    # Scan for SKILL.md and CLAUDE.md
    for pattern in ["SKILL.md", "CLAUDE.md"]:
        for skill_file in sorted(repo_dir.rglob(pattern)):
            try:
                rel = skill_file.relative_to(repo_dir)
                if len(rel.parts) > 5:
                    continue
            except ValueError:
                continue

            skill_dir_str = str(skill_file.parent)
            if skill_dir_str in seen_dirs:
                continue

            # Skip root CLAUDE.md
            if pattern == "CLAUDE.md" and skill_file.parent == repo_dir:
                continue

            skill = _parse_skill_dir(skill_file.parent, repo_name)
            if skill:
                plugin.skills.append(skill)
                seen_dirs.add(skill_dir_str)

    # Scan for commands/*.md and agents/*.md recursively
    for md_file in sorted(repo_dir.rglob("commands/*.md")):
        try:
            rel = md_file.relative_to(repo_dir)
            if len(rel.parts) > 6:
                continue
        except ValueError:
            continue
        fm = _parse_yaml_frontmatter(md_file)
        plugin.commands.append(ClaudeSkill(
            name=fm.get("name", md_file.stem),
            description=fm.get("description", f"Command: {md_file.stem}"),
            path=str(md_file.relative_to(repo_dir)),
            source_repo=repo_name,
            content_file=str(md_file),
            skill_type="command",
        ))

    for md_file in sorted(repo_dir.rglob("agents/*.md")):
        try:
            rel = md_file.relative_to(repo_dir)
            if len(rel.parts) > 6:
                continue
        except ValueError:
            continue
        fm = _parse_yaml_frontmatter(md_file)
        plugin.agents.append(ClaudeSkill(
            name=fm.get("name", md_file.stem),
            description=fm.get("description", f"Agent: {md_file.stem}"),
            path=str(md_file.relative_to(repo_dir)),
            source_repo=repo_name,
            content_file=str(md_file),
            skill_type="agent",
        ))

    return plugin
