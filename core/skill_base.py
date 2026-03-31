"""Noxen - Skill Interface.

Every skill (plugin) must subclass `Skill` and implement `execute()`.
The SkillManager auto-discovers any .py file in /skills that contains
a class inheriting from Skill.

Skill authors only need to:
  1. Subclass Skill
  2. Fill in the `metadata` class variable
  3. Implement async execute()
  4. Optionally override setup() / teardown()
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SkillCategory(str, Enum):
    CODE_ANALYSIS = "code_analysis"
    CODE_GENERATION = "code_generation"
    SEARCH = "search"
    DEVOPS = "devops"
    DATA = "data"
    INTEGRATION = "integration"
    UTILITY = "utility"
    CUSTOM = "custom"


class SkillPriority(int, Enum):
    """Execution priority: lower number = runs first."""
    ORCHESTRATOR = 1   # Runs first, coordinates other skills
    PRIMARY = 2        # Core skills, run after orchestrator
    SECONDARY = 3      # Support skills
    UTILITY = 4        # Helper/utility skills
    BACKGROUND = 5     # Low-priority, background tasks


@dataclass
class SkillMetadata:
    """Describes a skill for the registry and the LLM tool-use layer."""
    name: str
    description: str
    version: str = "0.1.0"
    author: str = "unknown"
    category: SkillCategory = SkillCategory.CUSTOM
    tags: list[str] = field(default_factory=list)
    # Parameter schema (JSON-Schema style) so the LLM knows what to pass
    parameters: dict[str, Any] = field(default_factory=dict)
    # Whether the skill is safe to auto-execute without user confirmation
    auto_approve: bool = False
    # Execution priority (1=orchestrator, 5=background)
    priority: int = 3
    # Names of skills this skill depends on / can invoke
    depends_on: list[str] = field(default_factory=list)


@dataclass
class SkillResult:
    """Standardized return type for all skills."""
    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Skill(abc.ABC):
    """Base class every Noxen skill must inherit from."""

    metadata: SkillMetadata  # Must be set by subclass
    hub: Any = None          # Injected by SkillManager — allows calling other skills

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "metadata", None) and not abc.ABC in cls.__bases__:
            raise TypeError(
                f"Skill subclass '{cls.__name__}' must define a 'metadata' class variable "
                f"of type SkillMetadata."
            )

    async def setup(self) -> None:
        """Called once when the skill is loaded. Override for init logic."""

    async def teardown(self) -> None:
        """Called when the skill is unloaded. Override for cleanup."""

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Run the skill with the given parameters. Must be implemented."""
        ...

    async def call_skill(self, skill_name: str, **kwargs: Any) -> SkillResult:
        """Invoke another skill by name. Only works if hub is injected."""
        if not self.hub:
            return SkillResult(success=False, error="Hub not available — skill not managed")
        return await self.hub.execute_skill(skill_name=skill_name, **kwargs)

    def to_tool_schema(self) -> dict[str, Any]:
        """Export as an OpenAI-compatible tool definition for LLM function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.metadata.name,
                "description": self.metadata.description,
                "parameters": self.metadata.parameters or {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }

    def __repr__(self) -> str:
        return f"<Skill: {self.metadata.name} v{self.metadata.version}>"
