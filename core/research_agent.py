"""Noxen - Research Agent.

Orchestrator del pipeline di ricerca autonoma.
Detecta lacune nella knowledge base, cerca su GitHub e web,
analizza repo, genera skill, e le salva nel KB.

Pipeline: detect_gap → search_github → clone_analyze → web_research → build_skills → save
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.logger import get_logger
from core.research.github_client import GitHubClient, RepoCandidate
from core.research.repo_analyzer import RepoAnalyzer, RepoAnalysis
from core.research.web_researcher import WebResearcher, WebResearchResult
from core.research.skill_builder import SkillBuilder, SkillDefinition, SkillBuildResult

logger = get_logger("noxen.research_agent")


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class ResearchRequest:
    """Richiesta di ricerca."""
    query: str
    context: str = ""  # contesto aggiuntivo dalla conversazione
    language: str | None = None  # filtro linguaggio
    max_repos: int = 5
    max_web_results: int = 10
    auto_save: bool = True  # salva skills automaticamente nel KB


@dataclass
class ResearchResult:
    """Risultato completo della ricerca."""
    query: str
    repos_found: list[RepoCandidate] = field(default_factory=list)
    repos_analyzed: list[RepoAnalysis] = field(default_factory=list)
    web_results: list[WebResearchResult] = field(default_factory=list)
    skills_generated: list[SkillDefinition] = field(default_factory=list)
    skills_saved: int = 0
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Research Agent ───────────────────────────────────────────────────

class ResearchAgent:
    """Agente di ricerca autonomo.

    Orchestra il pipeline completo:
    1. Cerca repo GitHub rilevanti
    2. Clona e analizza i migliori
    3. Ricerca web per documentazione/tutorial
    4. Genera skill definitions con LLM
    5. Salva nel knowledge base
    """

    def __init__(
        self,
        github_client: GitHubClient | None = None,
        repo_analyzer: RepoAnalyzer | None = None,
        web_researcher: WebResearcher | None = None,
        skill_builder: SkillBuilder | None = None,
        knowledge_base: Any = None,
        event_router: Any = None,
        skill_repository: Any = None,
        skill_board_reviewer: Any = None,
    ) -> None:
        self._github = github_client
        self._analyzer = repo_analyzer
        self._web = web_researcher
        self._skill_builder = skill_builder
        self._kb = knowledge_base
        self._events = event_router
        self._skill_repo = skill_repository
        self._board_reviewer = skill_board_reviewer
        self._logger = get_logger("research_agent")

    async def research(self, request: ResearchRequest) -> ResearchResult:
        """Esegui il pipeline di ricerca completo.

        Args:
            request: ResearchRequest con query e parametri.

        Returns:
            ResearchResult con tutti i dati raccolti.
        """
        import time
        start = time.monotonic()
        result = ResearchResult(query=request.query)

        # ── License enforcement ──
        try:
            from core.tenants.repository import TenantRepository
            _repo = TenantRepository()
            from core.qdrant_client import DEFAULT_TENANT
            _tenant_id = getattr(self, "_tenant_id", DEFAULT_TENANT)
            _can, _reason = await _repo.increment_research_session(_tenant_id)
            if not _can:
                result.errors.append(_reason)
                result.duration_s = time.monotonic() - start
                return result
        except Exception as _le:
            pass  # License check failure should not block research

        await self._emit("research_start", {"query": request.query})

        try:
            # Step 1: Search GitHub
            if self._github:
                result.repos_found = await self._search_github(request)
                await self._emit("github_search_done", {
                    "repos_found": len(result.repos_found),
                })

            # Step 2: Analyze top repos
            if self._analyzer and result.repos_found:
                result.repos_analyzed = await self._analyze_repos(
                    result.repos_found[:request.max_repos]
                )
                await self._emit("repos_analyzed", {
                    "repos_analyzed": len(result.repos_analyzed),
                })

            # Step 3: Web research
            if self._web:
                web_result = await self._web_research(request)
                if web_result:
                    result.web_results = [web_result]
                    await self._emit("web_research_done", {
                        "results": web_result.total_results,
                    })

            # Step 4: Build skills
            if self._skill_builder:
                build_result = await self._build_skills(
                    request, result.repos_analyzed, result.web_results
                )
                result.skills_generated = build_result.skills
                result.errors.extend(build_result.errors)
                await self._emit("skills_built", {
                    "skills": len(result.skills_generated),
                })

            # Step 5: Save to SkillRepository (or KB fallback)
            if request.auto_save and (self._skill_repo or self._kb) and result.skills_generated:
                result.skills_saved = await self._save_skills(result.skills_generated)
                await self._emit("skills_saved", {
                    "saved": result.skills_saved,
                })

        except Exception as e:
            result.errors.append(str(e))
            self._logger.error(f"Research pipeline failed: {e}")
            await self._emit("research_error", {"error": str(e)})

        result.duration_s = time.monotonic() - start
        await self._emit("research_complete", {
            "duration_s": result.duration_s,
            "repos": len(result.repos_found),
            "skills": len(result.skills_generated),
            "saved": result.skills_saved,
        })

        return result

    async def quick_search(self, query: str, limit: int = 5) -> list[RepoCandidate]:
        """Ricerca rapida su GitHub senza analisi completa.

        Utile per suggerimenti veloci.
        """
        if not self._github:
            return []

        try:
            candidates = await self._github.search_repos(query, limit=limit)
            return self._github.rank_candidates(candidates, query)
        except Exception as e:
            self._logger.error(f"Quick search failed: {e}")
            return []

    async def detect_knowledge_gap(
        self,
        query: str,
        existing_skills: list[str] | None = None,
    ) -> bool:
        """Detecta se c'e' una lacuna nella knowledge base.

        Ritorna True se il topic non e' coperto dalle skill esistenti.
        """
        if not existing_skills:
            return True

        q_words = set(query.lower().split())
        for skill_name in existing_skills:
            skill_words = set(skill_name.lower().replace("-", " ").split())
            overlap = len(q_words & skill_words)
            if overlap >= len(q_words) * 0.5:
                return False  # Coperto abbastanza

        return True

    async def _search_github(self, request: ResearchRequest) -> list[RepoCandidate]:
        """Step 1: Cerca repo su GitHub."""
        try:
            candidates = await self._github.search_repos(
                request.query,
                language=request.language,
                limit=request.max_repos * 2,  # cerchiamo il doppio per il ranking
            )
            ranked = self._github.rank_candidates(candidates, request.query)
            return ranked[:request.max_repos]
        except Exception as e:
            self._logger.error(f"GitHub search failed: {e}")
            return []

    async def _analyze_repos(
        self,
        candidates: list[RepoCandidate],
    ) -> list[RepoAnalysis]:
        """Step 2: Analizza i top repo."""
        analyses: list[RepoAnalysis] = []

        for candidate in candidates:
            try:
                analysis = await self._analyzer.clone_and_analyze(candidate.url)
                if analysis and analysis.file_count > 0:
                    analyses.append(analysis)
            except Exception as e:
                self._logger.warning(f"Analysis failed for {candidate.full_name}: {e}")

        return analyses

    async def _web_research(self, request: ResearchRequest) -> WebResearchResult | None:
        """Step 3: Ricerca web."""
        try:
            return await self._web.search(
                request.query,
                num_results=request.max_web_results,
            )
        except Exception as e:
            self._logger.error(f"Web research failed: {e}")
            return None

    async def _build_skills(
        self,
        request: ResearchRequest,
        analyses: list[RepoAnalysis],
        web_results: list[WebResearchResult],
    ) -> SkillBuildResult:
        """Step 4: Genera skill con LLM."""
        try:
            return await self._skill_builder.build_skills(
                query=request.query,
                repo_analyses=analyses,
                web_results=web_results,
            )
        except Exception as e:
            self._logger.error(f"Skill building failed: {e}")
            return SkillBuildResult(errors=[str(e)])

    async def _save_skills(
        self, skills: list[SkillDefinition], tenant_id: str = "global"
    ) -> int:
        """Step 5: Salva skill nel SkillRepository con lifecycle.

        Flow: crea Skill DRAFT → board review → APPROVED.
        Fallback: salva nella KB generica se repo non disponibile.
        """
        saved = 0
        for skill_def in skills:
            try:
                if self._skill_repo:
                    # Usa SkillRepository con lifecycle completo
                    from core.skills.lifecycle import (
                        Skill, SkillStatus, SkillSource, SkillMetrics,
                    )
                    skill_id = f"skill_{skill_def.name}_{tenant_id}".replace(" ", "_").lower()
                    skill = Skill(
                        id=skill_id,
                        name=skill_def.name,
                        technology=skill_def.category,
                        version="1.0.0",
                        status=SkillStatus.DRAFT,
                        source=SkillSource.RESEARCH_AGENT,
                        skill_md=(
                            f"# {skill_def.name}\n\n"
                            f"{skill_def.description}\n\n"
                            f"{skill_def.content}"
                        ),
                        source_repos=skill_def.source_repos,
                        source_urls=skill_def.source_urls,
                        tenant_id=tenant_id,
                        metrics=SkillMetrics(
                            skill_id=skill_id,
                            confidence_score=skill_def.confidence,
                        ),
                    )

                    # Salva come DRAFT
                    await self._skill_repo.save(skill)

                    # Avvia board review in background
                    if self._board_reviewer:
                        asyncio.create_task(
                            self._board_reviewer.submit_for_review(skill)
                        )

                    saved += 1
                else:
                    # Fallback: salva nella KB generica
                    if self._kb and hasattr(self._kb, "add_skill"):
                        await self._kb.add_skill({
                            "name": skill_def.name,
                            "description": skill_def.description,
                            "category": skill_def.category,
                            "tags": skill_def.tags,
                            "content": skill_def.content,
                            "confidence": skill_def.confidence,
                        })
                        saved += 1
                    elif self._kb and hasattr(self._kb, "add"):
                        await self._kb.add(
                            f"skill:{skill_def.name}",
                            skill_def.content,
                            metadata={
                                "name": skill_def.name,
                                "category": skill_def.category,
                                "tags": ",".join(skill_def.tags),
                            },
                        )
                        saved += 1

            except Exception as e:
                self._logger.warning(f"Failed to save skill {skill_def.name}: {e}")

        return saved

    async def _emit(self, event_type: str, data: dict) -> None:
        """Emetti evento se event_router disponibile."""
        if self._events and hasattr(self._events, "emit"):
            try:
                await self._events.emit(event_type, data)
            except Exception:
                pass  # Non bloccare il pipeline per errori di evento
