"""Noxen - Skill Builder for Research Agent.

Genera skill automaticamente dai risultati della ricerca usando LLM.
Prende RepoAnalysis + WebResearchResult e produce SkillDefinition
pronte per essere salvate nel knowledge base.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.logger import get_logger

logger = get_logger("noxen.skill_builder")


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class SkillDefinition:
    """Definizione di una skill generata dalla ricerca."""
    name: str
    description: str
    category: str  # "api", "database", "security", "architecture", etc.
    tags: list[str] = field(default_factory=list)
    content: str = ""  # corpo della skill (istruzioni, pattern, best practices)
    source_repos: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0-1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SkillBuildResult:
    """Risultato della generazione skills."""
    skills: list[SkillDefinition] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    llm_tokens_used: int = 0


# ── Skill Builder ────────────────────────────────────────────────────

class SkillBuilder:
    """Genera skill dal risultato della ricerca usando LLM.

    Input: RepoAnalysis + WebResearchResult
    Output: Lista di SkillDefinition pronte per il knowledge base.
    """

    SKILL_CATEGORIES = [
        "api", "database", "security", "architecture", "performance",
        "testing", "devops", "frontend", "backend", "data",
    ]

    SYSTEM_PROMPT = """You are an expert developer creating reusable skill definitions.

Given research data about a technology/concept, generate structured skill definitions.
Each skill should be:
- Actionable: contains specific patterns, code examples, best practices
- Self-contained: can be understood without external context
- Focused: one clear topic per skill

Output valid JSON array of skills with this structure:
[{
    "name": "skill-name-kebab-case",
    "description": "One line description",
    "category": "one of: api, database, security, architecture, performance, testing, devops, frontend, backend, data",
    "tags": ["tag1", "tag2"],
    "content": "Detailed skill content with patterns, examples, best practices. Use markdown.",
    "confidence": 0.0-1.0
}]

Generate 1-5 skills from the research data. Focus on quality over quantity."""

    def __init__(self, llm_provider: Any = None) -> None:
        self._llm = llm_provider
        self._logger = get_logger("skill_builder")

    async def build_skills(
        self,
        query: str,
        repo_analyses: list[Any] | None = None,
        web_results: list[Any] | None = None,
        max_skills: int = 5,
    ) -> SkillBuildResult:
        """Genera skill definitions dai risultati della ricerca.

        Args:
            query: La query di ricerca originale.
            repo_analyses: Lista di RepoAnalysis.
            web_results: Lista di WebResearchResult.
            max_skills: Numero massimo di skill da generare.

        Returns:
            SkillBuildResult con le skill generate.
        """
        result = SkillBuildResult()

        if not self._llm:
            result.errors.append("LLM provider not configured")
            return result

        # Costruisci il prompt con i dati della ricerca
        prompt = self._build_prompt(query, repo_analyses, web_results, max_skills)

        try:
            # Chiama LLM
            llm_response = await self._call_llm(prompt)
            if not llm_response:
                result.errors.append("LLM returned empty response")
                return result

            # Parse risposta
            skills = self._parse_llm_response(llm_response, query, repo_analyses, web_results)
            result.skills = skills[:max_skills]

        except Exception as e:
            self._logger.error(f"Skill building failed: {e}")
            result.errors.append(str(e))

        return result

    def _build_prompt(
        self,
        query: str,
        repo_analyses: list[Any] | None = None,
        web_results: list[Any] | None = None,
        max_skills: int = 5,
    ) -> str:
        """Costruisci il prompt per l'LLM."""
        parts = [f"## Research Query: {query}\n"]

        # Repo data
        if repo_analyses:
            parts.append("## Repository Analysis\n")
            for ra in repo_analyses:
                parts.append(f"### {getattr(ra, 'repo_url', 'unknown')}")
                if hasattr(ra, "languages") and ra.languages:
                    parts.append(f"Languages: {', '.join(f'{k}({v})' for k, v in ra.languages.items())}")
                if hasattr(ra, "frameworks") and ra.frameworks:
                    parts.append(f"Frameworks: {', '.join(ra.frameworks)}")
                if hasattr(ra, "functions") and ra.functions:
                    func_names = [f.name for f in ra.functions[:20]]
                    parts.append(f"Key functions: {', '.join(func_names)}")
                if hasattr(ra, "classes") and ra.classes:
                    class_names = [c.name for c in ra.classes[:10]]
                    parts.append(f"Key classes: {', '.join(class_names)}")
                if hasattr(ra, "endpoints") and ra.endpoints:
                    eps = [f"{e.get('method', '')} {e.get('path', '')}" for e in ra.endpoints[:10]]
                    parts.append(f"Endpoints: {', '.join(eps)}")
                parts.append("")

        # Web results
        if web_results:
            parts.append("## Web Research\n")
            for wr in web_results:
                if hasattr(wr, "results"):
                    for r in wr.results[:5]:
                        title = getattr(r, "title", "")
                        snippet = getattr(r, "snippet", "")[:300]
                        parts.append(f"- **{title}**: {snippet}")
                parts.append("")

        parts.append(f"\nGenerate up to {max_skills} skill definitions from this research data.")
        return "\n".join(parts)

    async def _call_llm(self, prompt: str) -> str:
        """Chiama l'LLM provider."""
        if not self._llm:
            return ""

        # Supporta sia LLMProvider.query() che callable
        if hasattr(self._llm, "query"):
            response = await self._llm.query(prompt, system=self.SYSTEM_PROMPT)
            # LLMProvider ritorna dict con 'response'
            if isinstance(response, dict):
                return response.get("response", "")
            return str(response)
        elif callable(self._llm):
            return await self._llm(prompt)
        else:
            return ""

    def _parse_llm_response(
        self,
        response: str,
        query: str,
        repo_analyses: list[Any] | None = None,
        web_results: list[Any] | None = None,
    ) -> list[SkillDefinition]:
        """Parse la risposta LLM in SkillDefinition."""
        skills: list[SkillDefinition] = []

        # Estrai JSON dalla risposta (potrebbe essere wrappato in markdown code blocks)
        json_str = self._extract_json(response)
        if not json_str:
            self._logger.warning("No JSON found in LLM response")
            return skills

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            self._logger.error(f"JSON parse error: {e}")
            return skills

        if not isinstance(data, list):
            data = [data]

        # Raccogli source info
        source_repos = []
        if repo_analyses:
            for ra in repo_analyses:
                url = getattr(ra, "repo_url", "")
                if url:
                    source_repos.append(url)

        source_urls = []
        if web_results:
            for wr in web_results:
                if hasattr(wr, "results"):
                    for r in wr.results:
                        url = getattr(r, "url", "")
                        if url:
                            source_urls.append(url)

        for item in data:
            if not isinstance(item, dict):
                continue

            name = item.get("name", "").strip()
            if not name:
                continue

            category = item.get("category", "").lower()
            if category not in self.SKILL_CATEGORIES:
                category = "architecture"  # default

            confidence = item.get("confidence", 0.5)
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            confidence = max(0.0, min(1.0, float(confidence)))

            skills.append(SkillDefinition(
                name=name,
                description=item.get("description", ""),
                category=category,
                tags=item.get("tags", []),
                content=item.get("content", ""),
                source_repos=list(source_repos),
                source_urls=list(source_urls[:10]),
                confidence=confidence,
            ))

        return skills

    def _extract_json(self, text: str) -> str:
        """Estrai JSON da testo (supporta markdown code blocks)."""
        # Try markdown code block first
        match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Try raw JSON array
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return match.group(0)

        # Try raw JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0)

        return ""
