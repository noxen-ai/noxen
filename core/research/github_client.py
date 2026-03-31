"""Noxen - GitHub Client for Research Agent.

Cerca repo GitHub rilevanti per una tecnologia/concetto.
Usa REST API (PyGithub) e GraphQL (gql) per:
  - Ricerca repo per query testuale
  - Ricerca per topic specifici
  - Ranking per rilevanza
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.logger import get_logger

logger = get_logger("noxen.github_client")


@dataclass
class RepoCandidate:
    """Candidato repo GitHub per l'analisi."""
    full_name: str        # "owner/repo"
    url: str
    description: str
    stars: int
    language: str
    topics: list[str]
    last_updated: datetime
    size_kb: int
    has_readme: bool
    readme_preview: str   # primi 500 chars del README
    relevance_score: float = 0.0  # calcolato localmente


class GitHubClient:
    """Client GitHub con REST (PyGithub) e GraphQL.

    Cerca repo rilevanti per una tecnologia/concetto.
    """

    def __init__(self, token: str = "") -> None:
        from github import Github
        self._rest = Github(token) if token else Github()
        self._token = token
        self._logger = get_logger("github_client")

    async def search_repos(
        self,
        query: str,
        language: str | None = None,
        min_stars: int = 10,
        max_size_kb: int = 102400,  # 100MB
        limit: int = 10,
    ) -> list[RepoCandidate]:
        """Cerca repo GitHub rilevanti per una query.

        Usa REST API con filtri strutturati.
        Ordina per: stars DESC.
        Filtra out: fork, archived, size > max_size_kb.
        """
        # Costruisci query con filtri
        q_parts = [query]
        if language:
            q_parts.append(f"language:{language}")
        q_parts.append(f"stars:>={min_stars}")
        search_query = " ".join(q_parts)

        self._logger.info(f"GitHub search: {search_query}")

        try:
            results = self._rest.search_repositories(
                query=search_query,
                sort="stars",
                order="desc",
            )

            candidates: list[RepoCandidate] = []
            count = 0
            for repo in results:
                if count >= limit:
                    break

                # Filtra fork e archived
                if repo.fork or repo.archived:
                    continue

                # Filtra size
                if repo.size and repo.size > max_size_kb:
                    continue

                # README preview (best-effort)
                readme_preview = ""
                has_readme = False
                try:
                    readme = repo.get_readme()
                    if readme:
                        has_readme = True
                        content = readme.decoded_content.decode("utf-8", errors="replace")
                        readme_preview = content[:500]
                except Exception:
                    pass

                candidates.append(RepoCandidate(
                    full_name=repo.full_name,
                    url=repo.html_url,
                    description=repo.description or "",
                    stars=repo.stargazers_count,
                    language=repo.language or "",
                    topics=repo.get_topics() if hasattr(repo, "get_topics") else [],
                    last_updated=repo.updated_at or datetime.now(timezone.utc),
                    size_kb=repo.size or 0,
                    has_readme=has_readme,
                    readme_preview=readme_preview,
                ))
                count += 1

            self._logger.info(f"GitHub search returned {len(candidates)} candidates")
            return candidates

        except Exception as e:
            self._logger.error(f"GitHub search failed: {e}")
            return []

    async def get_repo_details(self, full_name: str) -> RepoCandidate | None:
        """Dettagli completi di un repo specifico.

        Include: README completo, topics, linguaggi usati.
        """
        try:
            repo = self._rest.get_repo(full_name)

            readme_preview = ""
            has_readme = False
            try:
                readme = repo.get_readme()
                if readme:
                    has_readme = True
                    content = readme.decoded_content.decode("utf-8", errors="replace")
                    readme_preview = content[:500]
            except Exception:
                pass

            return RepoCandidate(
                full_name=repo.full_name,
                url=repo.html_url,
                description=repo.description or "",
                stars=repo.stargazers_count,
                language=repo.language or "",
                topics=repo.get_topics() if hasattr(repo, "get_topics") else [],
                last_updated=repo.updated_at or datetime.now(timezone.utc),
                size_kb=repo.size or 0,
                has_readme=has_readme,
                readme_preview=readme_preview,
            )
        except Exception as e:
            self._logger.error(f"get_repo_details failed for {full_name}: {e}")
            return None

    async def search_by_topic(
        self,
        topics: list[str],
        limit: int = 5,
    ) -> list[RepoCandidate]:
        """Cerca via GitHub GraphQL per topic specifici.

        Più preciso della ricerca per testo libero.
        """
        if not self._token:
            # GraphQL richiede autenticazione
            self._logger.warning("GraphQL search requires token, falling back to REST")
            topic_query = " ".join(f"topic:{t}" for t in topics)
            return await self.search_repos(topic_query, limit=limit)

        try:
            from gql import gql, Client
            from gql.transport.aiohttp import AIOHTTPTransport

            transport = AIOHTTPTransport(
                url="https://api.github.com/graphql",
                headers={"Authorization": f"Bearer {self._token}"},
            )

            async with Client(transport=transport, fetch_schema_from_transport=False) as session:
                query = gql("""
                query SearchByTopic($query: String!, $limit: Int!) {
                  search(query: $query, type: REPOSITORY, first: $limit) {
                    nodes {
                      ... on Repository {
                        nameWithOwner
                        description
                        stargazerCount
                        primaryLanguage { name }
                        repositoryTopics(first: 10) {
                          nodes { topic { name } }
                        }
                        updatedAt
                        diskUsage
                        isArchived
                        isFork
                      }
                    }
                  }
                }
                """)

                topic_query = " ".join(f"topic:{t}" for t in topics)
                variables = {"query": topic_query, "limit": limit}
                result = await session.execute(query, variable_values=variables)

                candidates: list[RepoCandidate] = []
                for node in result.get("search", {}).get("nodes", []):
                    if not node or node.get("isArchived") or node.get("isFork"):
                        continue

                    repo_topics = [
                        t["topic"]["name"]
                        for t in node.get("repositoryTopics", {}).get("nodes", [])
                        if t and t.get("topic")
                    ]

                    lang = ""
                    if node.get("primaryLanguage"):
                        lang = node["primaryLanguage"].get("name", "")

                    updated = datetime.now(timezone.utc)
                    if node.get("updatedAt"):
                        try:
                            updated = datetime.fromisoformat(node["updatedAt"].replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass

                    candidates.append(RepoCandidate(
                        full_name=node.get("nameWithOwner", ""),
                        url=f"https://github.com/{node.get('nameWithOwner', '')}",
                        description=node.get("description", "") or "",
                        stars=node.get("stargazerCount", 0),
                        language=lang,
                        topics=repo_topics,
                        last_updated=updated,
                        size_kb=node.get("diskUsage", 0),
                        has_readme=False,  # GraphQL non fetcha il README qui
                        readme_preview="",
                    ))

                return candidates

        except Exception as e:
            self._logger.error(f"GraphQL search failed: {e}")
            # Fallback a REST
            topic_query = " ".join(f"topic:{t}" for t in topics)
            return await self.search_repos(topic_query, limit=limit)

    def rank_candidates(
        self,
        candidates: list[RepoCandidate],
        query: str,
    ) -> list[RepoCandidate]:
        """Rankizza i candidati per rilevanza.

        Score = stars(normalized) + recency + topic_match + description_match
        """
        if not candidates:
            return []

        max_stars = max(c.stars for c in candidates) or 1
        now = datetime.now(timezone.utc)
        q_lower = query.lower()
        q_words = set(q_lower.split())

        for c in candidates:
            # Stars score (0-0.3): log-normalized
            stars_score = 0.3 * (math.log1p(c.stars) / math.log1p(max_stars))

            # Recency score (0-0.2): decays over 2 years
            days_old = max((now - c.last_updated.replace(tzinfo=timezone.utc if c.last_updated.tzinfo is None else c.last_updated.tzinfo)).days, 0)
            recency_score = 0.2 * max(0, 1 - days_old / 730)

            # Topic match (0-0.3)
            topic_words = set(" ".join(c.topics).lower().split())
            topic_overlap = len(q_words & topic_words)
            topic_score = 0.3 * min(topic_overlap / max(len(q_words), 1), 1.0)

            # Description match (0-0.2)
            desc_lower = c.description.lower()
            desc_matches = sum(1 for w in q_words if w in desc_lower)
            desc_score = 0.2 * min(desc_matches / max(len(q_words), 1), 1.0)

            c.relevance_score = stars_score + recency_score + topic_score + desc_score

        candidates.sort(key=lambda c: c.relevance_score, reverse=True)
        return candidates
