"""Noxen - Context Gatherer.

Estratto da Orchestrator (Phase 2 Step 2.1).
Raccoglie tutto il contesto disponibile per una query:
  - Knowledge Base (skills, agents, docs)
  - Codebase RAG (solo se init_project() è stato fatto)
  - DB Schema (se DB connesso e query pertinente)
  - Skill Routing (competenze rilevanti)
  - Knowledge Skills (Phase 6: SkillRepository semantic search with confidence filter)

Costruisce il system prompt unificato.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from core.logger import get_logger

if TYPE_CHECKING:
    from core.knowledge_base import KnowledgeBase
    from core.db_connector import DBConnector, SchemaInfo
    from core.skill_router import SkillRouter
    from core.skills.repository import SkillRepository
    from core.skills.usage_tracker import SkillUsageTracker

logger = get_logger("noxen.context_gatherer")


class ContextGatherer:
    """Raccoglie contesto multi-source per il LLM."""

    # Minimum confidence for knowledge skills to be included in context
    MIN_SKILL_CONFIDENCE = 0.4

    def __init__(
        self,
        knowledge_base: KnowledgeBase | None = None,
        project_manager: Any = None,
        skill_router: SkillRouter | None = None,
        skill_repository: SkillRepository | None = None,
        usage_tracker: SkillUsageTracker | None = None,
    ) -> None:
        self.knowledge_base = knowledge_base
        self.project_manager = project_manager
        self.skill_router = skill_router
        self.skill_repository = skill_repository
        self.usage_tracker = usage_tracker

        # Riferimenti esterni settati dall'Orchestrator
        self.db: DBConnector | None = None
        self.db_schema: SchemaInfo | None = None
        self.ecosystem: Any = None  # EcosystemMap
        self.initialized: bool = False

    async def gather(
        self,
        question: str,
        service: str = "",
        use_db: bool = True,
    ) -> dict[str, Any]:
        """Raccoglie tutto il contesto disponibile per una domanda.

        Funziona SEMPRE — anche senza init_project():
        - Knowledge Base: sempre disponibile (15K docs indicizzati)
        - Codebase RAG: solo se init_project() è stato chiamato
        - DB Schema: solo se DB connesso
        - Skill Routing: solo se plugin scansionati

        Returns:
            dict con chiavi: system_prompt, kb_results, rag_results, db_active, skills_matched
        """
        # 0. Knowledge Base (sempre disponibile)
        kb_context = ""
        kb_count = 0
        if self.knowledge_base:
            try:
                kb_results = await self.knowledge_base.search(question, n_results=5)
                if kb_results:
                    kb_count = len(kb_results)
                    kb_context = "CONOSCENZA INTERNA (Skills & Agents):\n"
                    for r in kb_results:
                        meta = r.get("metadata", {})
                        source = f"{meta.get('plugin', '?')}/{meta.get('file_path', '?')}"
                        kb_context += f"\n--- [{meta.get('type', 'doc')}] {source} ---\n{r.get('document', '')}\n"
            except Exception as e:
                logger.warning(f"Knowledge base search fallita: {e}")

        # 1. RAG Search (codebase utente — solo se init)
        rag_context = ""
        rag_count = 0
        if self.initialized and self.project_manager:
            try:
                if service:
                    results = self.project_manager.search(service, question, n_results=5)
                else:
                    all_results = []
                    for proj_name in self.project_manager.projects:
                        try:
                            r = self.project_manager.search(proj_name, question, n_results=3)
                            all_results.extend(r)
                        except Exception:
                            continue
                    results = sorted(all_results, key=lambda x: x.get("distance", 1))[:8]

                if results:
                    rag_count = len(results)
                    rag_context = "CODICE RILEVANTE:\n"
                    for r in results:
                        meta = r.get("metadata", {})
                        source = meta.get("file_path", meta.get("source", "unknown"))
                        rag_context += f"\n--- {source} ---\n{r.get('document', '')}\n"
            except Exception as e:
                logger.warning(f"RAG search fallita: {e}")

        # 2. DB Context (solo se init + DB connesso)
        db_context = ""
        if use_db and self.db_schema and self.db:
            q_lower = question.lower()
            if any(kw in q_lower for kw in ["database", "tabella", "schema", "query", "model",
                                              "relazione", "colonna", "mysql", "db", "migration"]):
                db_context = "SCHEMA DATABASE:\n" + self.db.schema_to_text(self.db_schema)

        # 3. Skill Routing (runtime skills)
        relevant_skills: list[dict] = []
        if self.skill_router:
            relevant_skills = self.skill_router.route(question)
        skills_context = ""
        if relevant_skills:
            skills_context = "COMPETENZE DISPONIBILI:\n"
            for skill in relevant_skills[:5]:
                skills_context += f"- {skill['name']}: {skill['description'][:200]}\n"

        # 4. Knowledge Skills (Phase 6: SkillRepository with confidence filter)
        knowledge_skills_context = ""
        knowledge_skills_count = 0
        if self.skill_repository:
            try:
                knowledge_skills = await self.skill_repository.search(
                    query=question,
                    min_confidence=self.MIN_SKILL_CONFIDENCE,
                    limit=3,
                )
                if knowledge_skills:
                    knowledge_skills_count = len(knowledge_skills)
                    knowledge_skills_context = "KNOWLEDGE SKILLS (verificate):\n"
                    for ks in knowledge_skills:
                        knowledge_skills_context += (
                            f"\n--- [{ks.technology}] {ks.name} "
                            f"(confidence: {ks.metrics.confidence_score:.2f}) ---\n"
                            f"{ks.skill_md[:1500]}\n"
                        )
            except Exception as e:
                logger.warning(f"Knowledge skills search failed: {e}")

        system = self._build_system_prompt(
            kb_context, rag_context, db_context, skills_context, knowledge_skills_context,
        )

        return {
            "system_prompt": system,
            "kb_results": kb_count,
            "rag_results": rag_count,
            "db_active": bool(db_context),
            "skills_matched": len(relevant_skills),
            "knowledge_skills_matched": knowledge_skills_count,
        }

    def _build_system_prompt(
        self, kb: str, rag: str, db: str, skills: str, knowledge_skills: str = "",
    ) -> str:
        """Costruisci il system prompt con tutto il contesto."""
        parts = [
            "Sei Noxen, un AI orchestrator per ecosistemi multi-microservizi.",
            "Analizza il codice, il database e le architetture con precisione.",
            "Usa la conoscenza interna (skills, agenti, documentazione) per rispondere con competenza specializzata.",
            "Rispondi in italiano. Cita sempre le fonti specifiche.",
        ]

        if self.ecosystem:
            eco = self.ecosystem
            parts.append(
                f"\nECOSISTEMA: {eco.total_services} microservizi, "
                f"linguaggi: {', '.join(eco.languages)}, "
                f"framework: {', '.join(eco.frameworks)}"
            )

        if kb:
            parts.append(f"\n{kb}")
        if rag:
            parts.append(f"\n{rag}")
        if db:
            parts.append(f"\n{db}")
        if skills:
            parts.append(f"\n{skills}")
        if knowledge_skills:
            parts.append(f"\n{knowledge_skills}")

        return "\n".join(parts)
