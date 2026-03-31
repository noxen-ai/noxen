"""Noxen - Autonomous Development Engine.

.. deprecated::
    Questo modulo e' DEPRECATO a partire dalla Phase 4.
    Usare `core.execution.engine.ExecutionEngine` al suo posto.
    Questo file resta per retrocompatibilita' con gli endpoint legacy
    POST /api/orchestrator/engine/start|stop|status.
    Sara' rimosso in una versione futura.

Two-Loop Architecture ispirata a AI-Research-SKILLs (Autoresearch):
  BOOTSTRAP  — Spider DNA + KB research + Ideation + Goal generation
  INNER LOOP — Per ogni goal: genera istruzioni → Claude Code esegue → registra
  OUTER LOOP — Re-analisi Spider → score delta → decide CONTINUE/DONE
"""

from __future__ import annotations

import asyncio
import json
import warnings
from core.logger import get_logger
import os
import time
import yaml
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

logger = get_logger("noxen.engine")

warnings.warn(
    "core.neural_engine is deprecated. Use core.execution.engine.ExecutionEngine instead.",
    DeprecationWarning,
    stacklevel=2,
)

# ── Dataclass di stato ──────────────────────────────────────────────

@dataclass
class Goal:
    """Singolo obiettivo nella checklist."""
    id: str
    title: str
    description: str
    priority: int  # 1=critico, 2=alto, 3=medio
    category: str  # "optimization", "feature", "fix", "refactor", "security"
    status: str = "pending"  # pending, in_progress, done, skipped
    cycles_attempted: int = 0
    max_cycles: int = 3
    result_summary: str = ""
    score_before: int = 0
    score_after: int = 0


@dataclass
class CycleResult:
    """Risultato di un singolo ciclo inner loop."""
    cycle_id: int
    goal_id: str
    instructions_sent: str
    claude_output: str
    exit_code: int
    duration_s: float
    files_changed: list[str] = field(default_factory=list)
    success: bool = False


@dataclass
class EngineState:
    """Stato completo del motore, persistito in .neural/"""
    project_path: str
    project_name: str
    started_at: str = ""
    current_phase: str = "idle"  # idle, bootstrap, inner_loop, outer_loop, done
    current_cycle: int = 0
    total_cycles: int = 0
    health_score_initial: int = 0
    health_score_current: int = 0
    goals_total: int = 0
    goals_done: int = 0
    goals_skipped: int = 0
    is_running: bool = False
    stop_requested: bool = False


# ── Costanti ────────────────────────────────────────────────────────

MAX_TOTAL_CYCLES = 30       # safety: massimo cicli totali
CLAUDE_TIMEOUT = 600        # 10 min per singola invocazione Claude Code
SCORE_THRESHOLD = 90        # soglia per considerare il lavoro "finito"

# ── Engine ──────────────────────────────────────────────────────────

class NeuralEngine:
    """Motore di sviluppo autonomo.

    Usa Spider per analisi, KB per ricerca, LLM per ragionamento,
    e Claude Code CLI per l'esecuzione concreta del codice.
    """

    def __init__(self, orchestrator, knowledge_base):
        self.orchestrator = orchestrator
        self.llm = orchestrator.llm
        self.kb = knowledge_base
        self.state: Optional[EngineState] = None
        self.goals: list[Goal] = []
        self._neural_dir: Optional[Path] = None

    # ── Directories & State Persistence ─────────────────────────────

    def _init_neural_dir(self, project_path: str) -> Path:
        """Crea la directory .neural/ nel progetto target."""
        neural = Path(project_path) / ".neural"
        neural.mkdir(exist_ok=True)
        (neural / "cycles").mkdir(exist_ok=True)
        self._neural_dir = neural
        return neural

    def _save_state(self):
        """Salva lo stato corrente su disco."""
        if not self._neural_dir or not self.state:
            return
        with open(self._neural_dir / "project-state.yaml", "w") as f:
            yaml.dump(asdict(self.state), f, default_flow_style=False)

    def _save_goals(self):
        """Salva i goals su disco."""
        if not self._neural_dir:
            return
        with open(self._neural_dir / "goals.yaml", "w") as f:
            yaml.dump([asdict(g) for g in self.goals], f, default_flow_style=False)

    def _append_log(self, entry: str):
        """Appende al dev-log."""
        if not self._neural_dir:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._neural_dir / "dev-log.md", "a") as f:
            f.write(f"\n## [{timestamp}]\n{entry}\n")

    def _update_findings(self, content: str):
        """Aggiorna findings.md."""
        if not self._neural_dir:
            return
        with open(self._neural_dir / "findings.md", "w") as f:
            f.write(content)

    def _save_cycle(self, result: CycleResult):
        """Salva il dettaglio di un ciclo."""
        if not self._neural_dir:
            return
        path = self._neural_dir / "cycles" / f"cycle-{result.cycle_id:03d}.md"
        with open(path, "w") as f:
            f.write(f"# Cycle {result.cycle_id} — Goal: {result.goal_id}\n\n")
            f.write(f"## Istruzioni inviate a Claude Code\n\n```\n{result.instructions_sent}\n```\n\n")
            f.write(f"## Output Claude Code\n\n```\n{result.claude_output[:5000]}\n```\n\n")
            f.write(f"## Risultato\n\n")
            f.write(f"- Exit code: {result.exit_code}\n")
            f.write(f"- Durata: {result.duration_s:.0f}s\n")
            f.write(f"- Successo: {'Si' if result.success else 'No'}\n")
            if result.files_changed:
                f.write(f"- File modificati: {', '.join(result.files_changed)}\n")

    # ── LLM Helpers ─────────────────────────────────────────────────

    async def _llm_query(self, system: str, user_msg: str) -> str:
        """Query LLM non-streaming, raccoglie tutto il testo."""
        messages = [{"role": "user", "content": user_msg}]
        content = ""
        try:
            async for token in self.llm.stream_query(messages, system):
                content += token
        except Exception as e:
            content = f"[LLM Error: {e}]"
        return content

    async def _kb_search(self, query: str, n: int = 5) -> str:
        """Cerca nella Knowledge Base e ritorna contesto testuale."""
        try:
            results = await self.kb.search(query, n_results=n)
            docs = [r.get("document", "") for r in results] if results else []
            return "\n\n---\n\n".join(docs[:n])
        except Exception:
            return ""

    # ── Claude Code CLI ─────────────────────────────────────────────

    async def _run_claude_code(
        self, instructions: str, project_path: str, timeout: int = CLAUDE_TIMEOUT
    ) -> tuple[str, int]:
        """Lancia Claude Code CLI in modalita' non-interattiva.

        Usa `claude -p "istruzioni" --output-format text` come subprocess.
        Ritorna (output, exit_code).
        """
        cmd = [
            "claude", "-p", instructions,
            "--output-format", "text",
            "--no-session-persistence",
        ]

        logger.info(f"[Engine] Lancio Claude Code CLI ({len(instructions)} chars)...")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return f"[TIMEOUT dopo {timeout}s]", -1

            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                output += f"\n\n[STDERR]\n{stderr.decode('utf-8', errors='replace')}"

            logger.info(f"[Engine] Claude Code completato: exit={proc.returncode}, output={len(output)} chars")
            return output, proc.returncode or 0

        except FileNotFoundError:
            return "[ERRORE: claude CLI non trovato. Installa Claude Code.]", -1
        except Exception as e:
            return f"[ERRORE: {e}]", -1

    # ── BOOTSTRAP ───────────────────────────────────────────────────

    async def _bootstrap(
        self, project_path: str
    ) -> AsyncGenerator[dict, None]:
        """Fase iniziale: analizza, ricerca, idea, genera goals."""

        from core.spider import SpiderAnalysis

        yield {"phase": "bootstrap", "step": "discovery", "progress": 5,
               "detail": "Spider sta analizzando il progetto..."}

        # 1. Spider Discovery (sincrono — usa os.walk)
        spider = SpiderAnalysis(self.orchestrator, self.kb)
        dna = spider.discover(project_path)
        profile = dna.to_profile_text()

        yield {"phase": "bootstrap", "step": "discovery", "progress": 15,
               "detail": f"Progetto analizzato: {dna.code_files} file, {dna.total_loc:,} LOC, "
                         f"{len(dna.languages)} linguaggi, {len(dna.frameworks)} framework"}

        # 2. KB Research — best practice per questo tipo di progetto
        yield {"phase": "bootstrap", "step": "research", "progress": 20,
               "detail": "Ricerca best practice nella Knowledge Base..."}

        research_queries = [
            f"best practices {' '.join(dna.frameworks)} project optimization",
            f"{' '.join(dna.languages)} code quality architecture patterns",
            f"performance optimization {' '.join(dna.frameworks)}",
            f"security best practices {' '.join(dna.languages)} web application",
            f"testing strategy {' '.join(dna.frameworks)} CI/CD",
        ]

        kb_context = ""
        for q in research_queries:
            result = await self._kb_search(q, n=3)
            if result:
                kb_context += f"\n\n### Ricerca: {q}\n{result[:2000]}"

        yield {"phase": "bootstrap", "step": "research", "progress": 30,
               "detail": "Best practice trovate, avvio fase di ideazione..."}

        # 3. Ideazione — il cervello ragiona su cosa fare
        yield {"phase": "bootstrap", "step": "ideation", "progress": 35,
               "detail": "Neural sta ragionando su ottimizzazioni e nuove feature..."}

        ideation_system = (
            "Sei il Neural Development Engine, un architetto software autonomo.\n"
            "Hai analizzato un progetto e ora devi proporre obiettivi di sviluppo.\n\n"
            "Usa questi framework di ideazione:\n"
            "1. PROBLEM-FIRST: identifica pain point concreti nel codice\n"
            "2. ABSTRACTION LADDER: generalizza/specializza per trovare pattern\n"
            "3. CROSS-POLLINATION: porta best practice da altri framework/linguaggi\n"
            "4. FUTURE-PROOFING: cosa servira' tra 6 mesi?\n\n"
            f"PROFILO PROGETTO:\n{profile}\n\n"
            f"BEST PRACTICE TROVATE:\n{kb_context[:4000]}\n\n"
            "IMPORTANTE: Non proporre cose generiche. Sii SPECIFICO per questo progetto.\n"
            "Ogni proposta deve avere: titolo, descrizione concreta, priorita' (1-3), categoria.\n"
            "Categorie: optimization, feature, fix, refactor, security\n"
        )

        ideation_prompt = (
            "Analizza il progetto e genera una lista di 8-15 obiettivi di sviluppo.\n"
            "Per ognuno indica:\n"
            "- id: goal_NNN\n"
            "- title: titolo breve\n"
            "- description: cosa fare concretamente (3-5 righe con file specifici)\n"
            "- priority: 1 (critico), 2 (alto), 3 (medio)\n"
            "- category: optimization|feature|fix|refactor|security\n\n"
            "Includi:\n"
            "- Ottimizzazioni che lo sviluppatore non avrebbe pensato\n"
            "- Feature innovative basate sulle best practice trovate\n"
            "- Fix di architettura e sicurezza\n"
            "- Miglioramenti di performance concreti\n\n"
            "Rispondi SOLO con un blocco YAML valido, senza testo prima o dopo.\n"
            "Formato:\n"
            "```yaml\n"
            "goals:\n"
            "  - id: goal_001\n"
            "    title: ...\n"
            "    description: ...\n"
            "    priority: 1\n"
            "    category: optimization\n"
            "```"
        )

        ideation_response = await self._llm_query(ideation_system, ideation_prompt)

        yield {"phase": "bootstrap", "step": "ideation", "progress": 55,
               "detail": "Proposte generate, validazione e prioritizzazione..."}

        # 4. Parse dei goals
        goals = self._parse_goals(ideation_response)

        if not goals:
            # Fallback: genera almeno dei goal base
            goals = self._generate_fallback_goals(dna)

        # Ordina per priorita'
        goals.sort(key=lambda g: g.priority)
        self.goals = goals

        # 5. Reasoning loop — Neural raffina i goals
        yield {"phase": "bootstrap", "step": "reasoning", "progress": 60,
               "detail": f"{len(goals)} obiettivi identificati, ragionamento in corso..."}

        reasoning_system = (
            "Sei il Neural Development Engine. Hai generato una lista di obiettivi.\n"
            "Ora fai un passo indietro e ragiona:\n"
            "1. Questi obiettivi sono realistici per un singolo ciclo di sviluppo?\n"
            "2. L'ordine di priorita' e' corretto? (dipendenze tra goal?)\n"
            "3. Manca qualcosa di critico?\n"
            "4. C'e' qualcosa di troppo ambizioso da dividere in sotto-goal?\n\n"
            f"PROFILO:\n{profile}\n\n"
            f"GOALS ATTUALI:\n{yaml.dump([asdict(g) for g in goals], default_flow_style=False)}\n\n"
            "Rispondi con un'analisi breve (5-10 righe) e se necessario "
            "suggerisci modifiche. Se i goal vanno bene, scrivi 'GOALS APPROVATI'."
        )

        reasoning = await self._llm_query(reasoning_system, "Valuta i goals e approva o suggerisci modifiche.")

        yield {"phase": "bootstrap", "step": "reasoning", "progress": 70,
               "detail": "Ragionamento completato, finalizzazione piano..."}

        # 6. Salva tutto
        self.state = EngineState(
            project_path=project_path,
            project_name=dna.name,
            started_at=datetime.now().isoformat(),
            current_phase="bootstrap",
            health_score_initial=0,
            goals_total=len(goals),
        )

        self._save_state()
        self._save_goals()

        # Init dev-log e findings
        self._append_log(
            f"### Bootstrap completato\n\n"
            f"- Progetto: {dna.name}\n"
            f"- File: {dna.code_files}, LOC: {dna.total_loc:,}\n"
            f"- Linguaggi: {', '.join(dna.languages)}\n"
            f"- Framework: {', '.join(dna.frameworks)}\n"
            f"- Goals generati: {len(goals)}\n\n"
            f"**Ragionamento:**\n{reasoning[:1000]}"
        )

        self._update_findings(
            f"# Findings — {dna.name}\n\n"
            f"## Stato iniziale\n{profile}\n\n"
            f"## Obiettivi identificati\n"
            + "\n".join(f"- [{g.priority}] **{g.title}**: {g.description[:100]}..." for g in goals)
            + f"\n\n## Best Practice rilevanti\n{kb_context[:2000]}"
        )

        yield {"phase": "bootstrap", "step": "done", "progress": 75,
               "detail": f"Bootstrap completato: {len(goals)} obiettivi pronti",
               "goals": [asdict(g) for g in goals]}

    # ── INNER LOOP ──────────────────────────────────────────────────

    async def _inner_loop(
        self, goal: Goal, cycle_id: int
    ) -> AsyncGenerator[dict, None]:
        """Esegui un singolo goal: genera istruzioni, Claude Code, registra."""

        project_path = self.state.project_path

        yield {"phase": "inner_loop", "step": "planning", "progress": 0,
               "detail": f"Pianificazione goal: {goal.title}",
               "goal_id": goal.id, "cycle": cycle_id}

        # 1. Genera istruzioni dettagliate per Claude Code
        findings_path = self._neural_dir / "findings.md"
        findings_content = ""
        if findings_path.exists():
            findings_content = findings_path.read_text()[:3000]

        instruction_system = (
            "Sei il Neural Development Engine. Devi generare istruzioni PRECISE "
            "per Claude Code (un agente di sviluppo che scrivera' il codice).\n\n"
            "Le istruzioni devono essere:\n"
            "- SPECIFICHE: indica file esatti da creare/modificare\n"
            "- CONCRETE: includi pseudo-codice o struttura del codice\n"
            "- VERIFICABILI: indica come testare che funziona\n"
            "- AUTONOME: Claude Code deve poter eseguire senza chiedere nulla\n\n"
            f"PROGETTO: {self.state.project_name}\n"
            f"PATH: {project_path}\n\n"
            f"CONTESTO ACCUMULATO:\n{findings_content}\n"
        )

        instruction_prompt = (
            f"Genera le istruzioni per Claude Code per implementare questo goal:\n\n"
            f"**{goal.title}**\n{goal.description}\n"
            f"Categoria: {goal.category} | Priorita': {goal.priority}\n\n"
            f"Le istruzioni devono iniziare con 'Sei nel progetto {self.state.project_name}.' "
            f"e devono essere complete e auto-contenute.\n"
            f"Non usare placeholder — sii specifico con nomi di file, funzioni, classi.\n"
            f"Includi alla fine: 'Quando hai finito, esegui un test per verificare che funziona.'"
        )

        instructions = await self._llm_query(instruction_system, instruction_prompt)

        yield {"phase": "inner_loop", "step": "executing", "progress": 20,
               "detail": f"Invio istruzioni a Claude Code... ({len(instructions)} chars)",
               "goal_id": goal.id, "cycle": cycle_id}

        # 2. Esegui Claude Code
        t0 = time.time()
        output, exit_code = await self._run_claude_code(instructions, project_path)
        duration = time.time() - t0

        # 3. Determina file modificati (git diff)
        files_changed = await self._get_changed_files(project_path)

        # 4. Salva risultato
        cycle_result = CycleResult(
            cycle_id=cycle_id,
            goal_id=goal.id,
            instructions_sent=instructions,
            claude_output=output,
            exit_code=exit_code,
            duration_s=duration,
            files_changed=files_changed,
            success=exit_code == 0 and len(output) > 50,
        )

        self._save_cycle(cycle_result)

        yield {"phase": "inner_loop", "step": "done", "progress": 80,
               "detail": f"Claude Code completato in {duration:.0f}s — "
                         f"exit={exit_code}, {len(files_changed)} file modificati",
               "goal_id": goal.id, "cycle": cycle_id,
               "exit_code": exit_code,
               "files_changed": files_changed,
               "duration_s": duration,
               "_cycle_result": asdict(cycle_result)}

    # ── OUTER LOOP ──────────────────────────────────────────────────

    async def _outer_loop(
        self, goal: Goal, cycle_result: CycleResult, cycle_id: int
    ) -> AsyncGenerator[dict, None]:
        """Analizza il risultato, aggiorna goals, decide CONTINUE/DONE."""

        yield {"phase": "outer_loop", "step": "analyzing", "progress": 0,
               "detail": "Analisi del codice prodotto da Claude Code..."}

        # 1. Valuta il risultato
        eval_system = (
            "Sei il Neural Development Engine in fase di REVIEW.\n"
            "Claude Code ha appena eseguito delle modifiche al progetto.\n"
            "Valuta se il goal e' stato raggiunto.\n\n"
            f"GOAL: {goal.title}\n{goal.description}\n\n"
            f"EXIT CODE: {cycle_result.exit_code}\n"
            f"FILE MODIFICATI: {', '.join(cycle_result.files_changed) or 'nessuno'}\n"
            f"OUTPUT (primi 3000 chars):\n{cycle_result.claude_output[:3000]}\n"
        )

        evaluation = await self._llm_query(
            eval_system,
            "Valuta:\n"
            "1. Il goal e' stato completato? (SI/PARZIALE/NO)\n"
            "2. Qualita' del codice prodotto (1-10)\n"
            "3. Problemi riscontrati\n"
            "4. Prossimi passi consigliati\n\n"
            "Rispondi in modo strutturato."
        )

        # Parse della valutazione
        eval_lower = evaluation.lower()
        goal_completed = "si" in eval_lower[:200] and "no" not in eval_lower[:50]

        if goal_completed or goal.cycles_attempted >= goal.max_cycles:
            goal.status = "done" if goal_completed else "skipped"
            goal.result_summary = evaluation[:500]
            if goal_completed:
                self.state.goals_done += 1
            else:
                self.state.goals_skipped += 1

        yield {"phase": "outer_loop", "step": "evaluated", "progress": 50,
               "detail": f"Goal {'COMPLETATO' if goal_completed else 'da ritentare'}: {goal.title}",
               "goal_completed": goal_completed,
               "evaluation": evaluation[:500]}

        # 2. Aggiorna findings
        yield {"phase": "outer_loop", "step": "updating", "progress": 70,
               "detail": "Aggiornamento conoscenza accumulata..."}

        current_findings = ""
        if self._neural_dir:
            fp = self._neural_dir / "findings.md"
            if fp.exists():
                current_findings = fp.read_text()[:3000]

        findings_update_system = (
            "Sei il Neural Development Engine. Aggiorna il documento di findings.\n"
            "Integra le nuove informazioni mantenendo tutto il contesto precedente.\n\n"
            f"FINDINGS ATTUALI:\n{current_findings}\n\n"
            f"NUOVO CICLO:\n"
            f"- Goal: {goal.title}\n"
            f"- Risultato: {'Completato' if goal_completed else 'Non completato'}\n"
            f"- Valutazione: {evaluation[:500]}\n"
            f"- File modificati: {', '.join(cycle_result.files_changed)}"
        )

        updated_findings = await self._llm_query(
            findings_update_system,
            "Aggiorna findings.md integrando i nuovi risultati. Mantieni le sezioni: "
            "Stato Attuale, Obiettivi Completati, Lezioni Apprese, Prossimi Passi."
        )

        if updated_findings and "[LLM Error" not in updated_findings:
            self._update_findings(updated_findings)

        # 3. Salva stato
        self._save_goals()
        self._save_state()

        self._append_log(
            f"### Ciclo {cycle_id} — {goal.title}\n\n"
            f"- Risultato: {'Completato' if goal_completed else 'Non completato'}\n"
            f"- File: {', '.join(cycle_result.files_changed) or 'nessuno'}\n"
            f"- Durata: {cycle_result.duration_s:.0f}s\n"
            f"- Valutazione: {evaluation[:200]}"
        )

        # 4. Decide se continuare
        pending_goals = [g for g in self.goals if g.status == "pending"]
        all_done = len(pending_goals) == 0

        yield {"phase": "outer_loop", "step": "decision", "progress": 100,
               "detail": f"{'TUTTI I GOAL COMPLETATI' if all_done else f'{len(pending_goals)} goal rimanenti'}",
               "all_done": all_done,
               "goals_done": self.state.goals_done,
               "goals_remaining": len(pending_goals),
               "goals_total": self.state.goals_total}

    # ── MAIN RUN — Il Loop Autonomo ─────────────────────────────────

    async def run(
        self, project_path: str
    ) -> AsyncGenerator[dict, None]:
        """Loop autonomo completo: Bootstrap, (Inner, Outer)*, Done.

        Genera eventi SSE per il frontend.
        """
        logger.info(f"[Engine] === AVVIO Neural Development Engine su {project_path} ===")

        # Init
        self._init_neural_dir(project_path)
        cycle_id = 0

        # ── BOOTSTRAP ──
        yield {"phase": "start", "progress": 0,
               "detail": "Neural Development Engine avviato"}

        async for update in self._bootstrap(project_path):
            yield update

        if not self.goals:
            yield {"phase": "error", "progress": 100,
                   "detail": "Nessun goal generato. Controlla LLM e KB.", "done": True}
            return

        self.state.current_phase = "running"
        self.state.is_running = True
        self._save_state()

        yield {"phase": "loop_start", "progress": 0,
               "detail": f"Inizio loop autonomo: {len(self.goals)} goals da completare",
               "goals": [asdict(g) for g in self.goals]}

        # ── LOOP PRINCIPALE ──
        while cycle_id < MAX_TOTAL_CYCLES:

            # Check stop
            if self.state.stop_requested:
                yield {"phase": "stopped", "progress": 100,
                       "detail": "Stop richiesto dall'utente", "done": True}
                break

            # Trova prossimo goal
            pending = [g for g in self.goals if g.status == "pending"]
            if not pending:
                break

            goal = pending[0]
            goal.status = "in_progress"
            goal.cycles_attempted += 1
            cycle_id += 1
            self.state.current_cycle = cycle_id
            self.state.total_cycles = cycle_id

            logger.info(f"[Engine] === Ciclo {cycle_id}: {goal.title} (tentativo {goal.cycles_attempted}/{goal.max_cycles}) ===")

            yield {"phase": "cycle_start", "cycle": cycle_id,
                   "goal": asdict(goal),
                   "detail": f"Ciclo {cycle_id}: {goal.title}",
                   "goals_done": self.state.goals_done,
                   "goals_total": self.state.goals_total}

            # ── INNER LOOP ──
            cycle_result = None
            async for update in self._inner_loop(goal, cycle_id):
                yield update
                # Cattura il cycle_result dall'ultimo update
                if update.get("step") == "done" and "_cycle_result" in update:
                    cr = update["_cycle_result"]
                    cycle_result = CycleResult(**{k: v for k, v in cr.items()})

            if not cycle_result:
                goal.status = "pending"
                continue

            # ── OUTER LOOP ──
            async for update in self._outer_loop(goal, cycle_result, cycle_id):
                yield update

            # Se il goal non e' completato e ha ancora tentativi, rimettilo pending
            if goal.status == "in_progress":
                if goal.cycles_attempted < goal.max_cycles:
                    goal.status = "pending"
                else:
                    goal.status = "skipped"
                    self.state.goals_skipped += 1

            self._save_goals()
            self._save_state()

        # ── FINALIZZAZIONE ──
        self.state.current_phase = "done"
        self.state.is_running = False
        self._save_state()

        # Report finale
        final_report = await self._generate_final_report()

        yield {"phase": "done", "progress": 100,
               "detail": f"Neural Development Engine completato: "
                         f"{self.state.goals_done}/{self.state.goals_total} goals, "
                         f"{cycle_id} cicli totali",
               "report": final_report,
               "goals_done": self.state.goals_done,
               "goals_skipped": self.state.goals_skipped,
               "goals_total": self.state.goals_total,
               "total_cycles": cycle_id,
               "done": True}

        logger.info(f"[Engine] === COMPLETATO: {self.state.goals_done}/{self.state.goals_total} goals in {cycle_id} cicli ===")

    # ── Helpers ─────────────────────────────────────────────────────

    def _parse_goals(self, llm_response: str) -> list[Goal]:
        """Estrae goals dal YAML generato dall'LLM."""
        try:
            # Cerca blocco yaml nel response
            yaml_text = llm_response
            if "```yaml" in yaml_text:
                yaml_text = yaml_text.split("```yaml")[1].split("```")[0]
            elif "```" in yaml_text:
                yaml_text = yaml_text.split("```")[1].split("```")[0]

            data = yaml.safe_load(yaml_text)

            goals_data = data if isinstance(data, list) else data.get("goals", [])

            goals = []
            for i, g in enumerate(goals_data):
                goals.append(Goal(
                    id=g.get("id", f"goal_{i+1:03d}"),
                    title=g.get("title", f"Goal {i+1}"),
                    description=g.get("description", ""),
                    priority=int(g.get("priority", 2)),
                    category=g.get("category", "optimization"),
                ))

            logger.info(f"[Engine] Parsed {len(goals)} goals dal LLM")
            return goals

        except Exception as e:
            logger.error(f"[Engine] Errore parsing goals: {e}")
            return []

    def _generate_fallback_goals(self, dna) -> list[Goal]:
        """Genera goals di fallback basati sul DNA del progetto."""
        goals = [
            Goal(id="goal_001", title="Code Quality Audit",
                 description="Analizza e migliora la qualita del codice: rimuovi codice morto, "
                             "migliora naming, aggiungi type hints, riduci complessita ciclomatica.",
                 priority=1, category="refactor"),
            Goal(id="goal_002", title="Error Handling",
                 description="Implementa error handling consistente in tutto il progetto: "
                             "try/except specifici, logging strutturato, messaggi user-friendly.",
                 priority=1, category="fix"),
            Goal(id="goal_003", title="Performance Optimization",
                 description="Identifica e ottimizza i colli di bottiglia: query N+1, "
                             "caching mancante, I/O bloccante su main thread.",
                 priority=2, category="optimization"),
        ]

        if not dna.has_ci:
            goals.append(Goal(
                id="goal_004", title="CI/CD Pipeline",
                description="Crea una pipeline CI/CD base con lint, test, build.",
                priority=2, category="feature"))

        if dna.has_docker:
            goals.append(Goal(
                id="goal_005", title="Docker Optimization",
                description="Ottimizza Dockerfile: multi-stage build, .dockerignore, layer caching.",
                priority=3, category="optimization"))

        return goals

    async def _get_changed_files(self, project_path: str) -> list[str]:
        """Ritorna la lista dei file modificati (git diff)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "diff", "--name-only", "HEAD~1", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
            )
            stdout, _ = await proc.communicate()
            files = stdout.decode().strip().split("\n")
            return [f for f in files if f]
        except Exception:
            # Fallback: git status
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "diff", "--name-only",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=project_path,
                )
                stdout, _ = await proc.communicate()
                files = stdout.decode().strip().split("\n")
                return [f for f in files if f]
            except Exception:
                return []

    async def _generate_final_report(self) -> str:
        """Genera il report finale in Markdown."""
        if not self._neural_dir:
            return "# Report non disponibile"

        findings = ""
        findings_path = self._neural_dir / "findings.md"
        if findings_path.exists():
            findings = findings_path.read_text()

        report = f"# Neural Development Report — {self.state.project_name}\n\n"
        report += f"> Generato da Neural Development Engine | {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        report += f"## Riepilogo\n\n"
        report += f"| Metrica | Valore |\n|---|---|\n"
        report += f"| Goals completati | {self.state.goals_done}/{self.state.goals_total} |\n"
        report += f"| Goals saltati | {self.state.goals_skipped} |\n"
        report += f"| Cicli totali | {self.state.total_cycles} |\n"
        report += f"| Inizio | {self.state.started_at} |\n\n"

        report += f"## Obiettivi\n\n"
        for g in self.goals:
            icon = "V" if g.status == "done" else ">>" if g.status == "skipped" else "..."
            report += f"### [{icon}] {g.title}\n"
            report += f"- **Stato**: {g.status} | **Priorita**: {g.priority} | **Categoria**: {g.category}\n"
            report += f"- {g.description}\n"
            if g.result_summary:
                report += f"- **Risultato**: {g.result_summary[:200]}\n"
            report += "\n"

        if findings:
            report += f"## Findings\n\n{findings}\n"

        report += f"\n---\n*Report generato da Noxen Development Engine v0.2.0*\n"
        return report

    def request_stop(self):
        """Richiedi stop del loop (graceful)."""
        if self.state:
            self.state.stop_requested = True
            self._save_state()
            logger.info("[Engine] Stop richiesto")
