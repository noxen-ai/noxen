"""Noxen - Skill Router.

Estratto da Orchestrator (Phase 2 Step 2.2).
Seleziona le skill rilevanti per una query:
  1. Keyword matching (veloce, zero LLM)
  2. Semantic search via Qdrant collection "skills" (se disponibile)
"""

from __future__ import annotations

from typing import Any

from core.logger import get_logger

logger = get_logger("noxen.skill_router")

# Mappa delle skill routing per contesto (ispirata ad AI-Research-SKILLs)
SKILL_ROUTING = {
    "security": ["security", "pentesting", "vulnerability", "xss", "sql injection", "auth"],
    "database": ["database", "mysql", "schema", "query", "tabella", "migration", "model"],
    "api": ["endpoint", "route", "api", "rest", "controller", "middleware"],
    "frontend": ["vue", "react", "angular", "component", "template", "css", "layout"],
    "devops": ["docker", "deploy", "ci/cd", "pipeline", "container", "kubernetes"],
    "architecture": ["architettura", "pattern", "struttura", "refactor", "microservizi", "comunicazione"],
    "performance": ["performance", "ottimizzazione", "cache", "redis", "slow", "lento"],
    "testing": ["test", "unit test", "integration", "coverage", "mock"],
}


class SkillRouter:
    """Router di competenze per le query."""

    def __init__(self, plugin_composer: Any = None) -> None:
        self._plugin_composer = plugin_composer
        self._cache: list[dict] = []

    def refresh_cache(self) -> int:
        """Ricarica la cache delle skill dal plugin_composer.

        Returns:
            Numero di skill caricate.
        """
        if self._plugin_composer:
            self._cache = self._plugin_composer.get_all_skills()
        else:
            self._cache = []
        return len(self._cache)

    @property
    def cache_size(self) -> int:
        """Numero di skill in cache."""
        return len(self._cache)

    def route(self, question: str, max_results: int = 10) -> list[dict]:
        """Seleziona le skill rilevanti per la domanda (keyword matching).

        Args:
            question: La domanda dell'utente
            max_results: Numero massimo di skill da ritornare

        Returns:
            Lista di skill dict con name, description, tags, etc.
        """
        if not self._cache:
            return []

        q_lower = question.lower()
        matched_categories: set[str] = set()

        for category, keywords in SKILL_ROUTING.items():
            if any(kw in q_lower for kw in keywords):
                matched_categories.add(category)

        if not matched_categories:
            return []

        relevant = []
        for skill in self._cache:
            skill_text = f"{skill.get('name', '')} {skill.get('description', '')} {' '.join(skill.get('tags', []))}".lower()
            for cat in matched_categories:
                if any(kw in skill_text for kw in SKILL_ROUTING[cat]):
                    relevant.append(skill)
                    break

        return relevant[:max_results]

    async def semantic_route(self, question: str, n_results: int = 5) -> list[dict]:
        """Ricerca semantica delle skill via Qdrant collection "skills".

        Usa FastEmbed per generare l'embedding della domanda e cerca
        nella collection Qdrant "skills" i documenti più simili.

        Falls back to keyword route() se Qdrant non è disponibile.

        Args:
            question: La domanda dell'utente
            n_results: Numero di risultati

        Returns:
            Lista di skill dict dal Qdrant search.
        """
        try:
            from core.qdrant_client import NoxenQdrantClient
            from core.embedding_provider import FastEmbedProvider

            instance = NoxenQdrantClient.get_instance()
            client = instance.client

            # Genera embedding della query
            provider = FastEmbedProvider.get_instance()
            vectors = provider.embed([question])
            if not vectors:
                return self.route(question)

            from qdrant_client.models import Filter, FieldCondition, MatchValue

            results = client.query_points(
                collection_name="skills",
                query=vectors[0],
                limit=n_results,
            )

            matched = []
            for point in results.points:
                payload = point.payload or {}
                matched.append({
                    "name": payload.get("file_path", "unknown"),
                    "description": payload.get("document", "")[:300],
                    "score": point.score,
                    "plugin": payload.get("plugin", ""),
                    "type": payload.get("type", "skill"),
                })

            return matched if matched else self.route(question)

        except (RuntimeError, ImportError, Exception) as e:
            logger.debug(f"Semantic route fallback to keyword: {e}")
            return self.route(question)
