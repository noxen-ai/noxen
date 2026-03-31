"""Noxen - Claude Code Executor for Execution Engine.

Wrapper per l'esecuzione di Claude Code CLI in sandbox:
  - Genera istruzioni strutturate per Claude Code
  - Esegue via subprocess con timeout
  - Raccoglie output, exit code, file modificati
  - Verifica il risultato via LLM

Step 4.3 della Phase 4.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("noxen.claude_executor")


# ── Constants ────────────────────────────────────────────────────────

CLAUDE_TIMEOUT_S = 600  # 10 min default per singola invocazione
MAX_OUTPUT_CHARS = 50_000  # Tronca output oltre questo limite


# ── Dataclass ────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """Risultato di un'esecuzione Claude Code."""

    goal_id: str
    instructions: str
    output: str
    exit_code: int
    duration_s: float
    files_changed: list[str] = field(default_factory=list)
    success: bool = False
    error: str = ""
    verification: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InstructionContext:
    """Contesto per generare istruzioni per Claude Code."""

    project_name: str
    project_path: str
    goal_title: str
    goal_description: str
    goal_category: str
    accumulated_context: str = ""
    constraints: list[str] = field(default_factory=list)


# ── ClaudeExecutor ──────────────────────────────────────────────────

class ClaudeExecutor:
    """Esegue Claude Code CLI con istruzioni strutturate.

    Responsabilita':
    - Generare istruzioni dettagliate da un goal
    - Invocare `claude -p` come subprocess
    - Raccogliere risultati e file modificati
    - Verificare il risultato via LLM callback
    """

    def __init__(
        self,
        llm_query_fn=None,
        timeout_s: int = CLAUDE_TIMEOUT_S,
    ) -> None:
        """
        Args:
            llm_query_fn: Async callable(system, user_msg) -> str per LLM queries.
                          Se None, usa istruzioni dirette senza LLM enhancement.
            timeout_s: Timeout per singola invocazione Claude Code.
        """
        self._llm_query = llm_query_fn
        self._timeout = timeout_s

    async def generate_instructions(
        self,
        context: InstructionContext,
    ) -> str:
        """Genera istruzioni per Claude Code da un goal.

        Se llm_query_fn e' disponibile, usa LLM per generare istruzioni
        dettagliate. Altrimenti, crea istruzioni template-based.

        Args:
            context: InstructionContext con tutti i dettagli.

        Returns:
            Stringa di istruzioni pronte per Claude Code.
        """
        if self._llm_query:
            return await self._generate_with_llm(context)
        return self._generate_template(context)

    async def check_availability(self) -> bool:
        """Verifica che Claude Code CLI sia disponibile nel PATH."""
        return shutil.which("claude") is not None

    async def execute(
        self,
        instructions: str,
        working_dir: str,
        goal_id: str = "",
    ) -> ExecutionResult:
        """Esegui Claude Code CLI con le istruzioni date.

        Args:
            instructions: Istruzioni da inviare a Claude Code.
            working_dir: Directory di lavoro (sandbox).
            goal_id: ID del goal per tracking.

        Returns:
            ExecutionResult con output, exit code, file modificati.
        """
        result = ExecutionResult(
            goal_id=goal_id,
            instructions=instructions,
            output="",
            exit_code=-1,
            duration_s=0.0,
        )

        # Pre-execution check
        if not await self.check_availability():
            result.error = (
                "Claude Code CLI non trovato nel PATH. "
                "Installa con: npm install -g @anthropic-ai/claude-code"
            )
            result.success = False
            return result

        t0 = time.time()

        try:
            output, exit_code = await self._run_claude_cli(
                instructions, working_dir
            )
            result.output = output[:MAX_OUTPUT_CHARS]
            result.exit_code = exit_code
            result.success = exit_code == 0 and len(output) > 50
            result.files_changed = await self._get_changed_files(working_dir)

        except asyncio.TimeoutError:
            result.error = f"Timeout after {self._timeout}s"
            result.exit_code = -1
        except FileNotFoundError:
            result.error = "Claude CLI not found. Install Claude Code."
            result.exit_code = -1
        except Exception as e:
            result.error = str(e)
            result.exit_code = -1

        result.duration_s = time.time() - t0

        logger.info(
            "claude_executor.executed",
            goal_id=goal_id,
            exit_code=result.exit_code,
            duration_s=round(result.duration_s, 1),
            files_changed=len(result.files_changed),
            success=result.success,
        )

        return result

    async def verify(
        self,
        result: ExecutionResult,
        goal_title: str,
        goal_description: str,
    ) -> str:
        """Verifica il risultato dell'esecuzione via LLM.

        Args:
            result: ExecutionResult da verificare.
            goal_title: Titolo del goal.
            goal_description: Descrizione del goal.

        Returns:
            Stringa con la valutazione. Vuota se nessun LLM disponibile.
        """
        if not self._llm_query:
            return ""

        system = (
            "Sei il Neural Development Engine in fase di REVIEW.\n"
            "Claude Code ha appena eseguito delle modifiche al progetto.\n"
            "Valuta se il goal e' stato raggiunto.\n\n"
            f"GOAL: {goal_title}\n{goal_description}\n\n"
            f"EXIT CODE: {result.exit_code}\n"
            f"FILE MODIFICATI: {', '.join(result.files_changed) or 'nessuno'}\n"
            f"OUTPUT (primi 3000 chars):\n{result.output[:3000]}\n"
        )

        prompt = (
            "Valuta:\n"
            "1. Il goal e' stato completato? (SI/PARZIALE/NO)\n"
            "2. Qualita' del codice prodotto (1-10)\n"
            "3. Problemi riscontrati\n"
            "4. Prossimi passi consigliati\n\n"
            "Rispondi in modo strutturato."
        )

        try:
            verification = await self._llm_query(system, prompt)
            result.verification = verification[:1000]
            return verification
        except Exception as e:
            logger.warning("claude_executor.verify_failed", error=str(e))
            return f"[Verification error: {e}]"

    # ── Internal ─────────────────────────────────────────────────────

    async def _run_claude_cli(
        self,
        instructions: str,
        working_dir: str,
    ) -> tuple[str, int]:
        """Lancia Claude Code CLI come subprocess.

        Usa `claude -p "istruzioni" --output-format text`.
        """
        cmd = [
            "claude", "-p", instructions,
            "--output-format", "text",
            "--no-session-persistence",
        ]

        logger.info(
            "claude_executor.launching",
            instructions_len=len(instructions),
            working_dir=working_dir,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise

        output = stdout.decode("utf-8", errors="replace")
        if stderr:
            stderr_text = stderr.decode("utf-8", errors="replace")
            if stderr_text.strip():
                output += f"\n\n[STDERR]\n{stderr_text}"

        return output, proc.returncode or 0

    async def _get_changed_files(self, working_dir: str) -> list[str]:
        """Ritorna file modificati via git diff."""
        try:
            # Try committed changes first
            proc = await asyncio.create_subprocess_exec(
                "git", "diff", "--name-only", "HEAD~1", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, _ = await proc.communicate()
            files = [f for f in stdout.decode().strip().split("\n") if f]
            if files:
                return files
        except Exception:
            pass

        try:
            # Fallback: uncommitted changes
            proc = await asyncio.create_subprocess_exec(
                "git", "diff", "--name-only",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, _ = await proc.communicate()
            files = [f for f in stdout.decode().strip().split("\n") if f]
            return files
        except Exception:
            return []

    async def _generate_with_llm(
        self,
        context: InstructionContext,
    ) -> str:
        """Genera istruzioni via LLM."""
        system = (
            "Sei il Neural Development Engine. Devi generare istruzioni PRECISE "
            "per Claude Code (un agente di sviluppo che scrivera' il codice).\n\n"
            "Le istruzioni devono essere:\n"
            "- SPECIFICHE: indica file esatti da creare/modificare\n"
            "- CONCRETE: includi pseudo-codice o struttura del codice\n"
            "- VERIFICABILI: indica come testare che funziona\n"
            "- AUTONOME: Claude Code deve poter eseguire senza chiedere nulla\n\n"
            f"PROGETTO: {context.project_name}\n"
            f"PATH: {context.project_path}\n\n"
        )

        if context.accumulated_context:
            system += f"CONTESTO ACCUMULATO:\n{context.accumulated_context[:4000]}\n\n"

        if context.constraints:
            system += "VINCOLI:\n"
            for c in context.constraints:
                system += f"- {c}\n"
            system += "\n"

        prompt = (
            f"Genera le istruzioni per Claude Code per implementare questo goal:\n\n"
            f"**{context.goal_title}**\n{context.goal_description}\n"
            f"Categoria: {context.goal_category}\n\n"
            f"Le istruzioni devono iniziare con "
            f"'Sei nel progetto {context.project_name}.' "
            f"e devono essere complete e auto-contenute.\n"
            f"Non usare placeholder — sii specifico.\n"
            f"Includi alla fine: "
            f"'Quando hai finito, esegui un test per verificare che funziona.'"
        )

        try:
            return await self._llm_query(system, prompt)
        except Exception as e:
            logger.warning("claude_executor.llm_failed", error=str(e))
            return self._generate_template(context)

    def _generate_template(self, context: InstructionContext) -> str:
        """Genera istruzioni template-based (senza LLM)."""
        parts = [
            f"Sei nel progetto {context.project_name}.",
            f"Il progetto si trova in: {context.project_path}",
            "",
            f"## Obiettivo: {context.goal_title}",
            "",
            context.goal_description,
            "",
            f"Categoria: {context.goal_category}",
        ]

        if context.constraints:
            parts.append("")
            parts.append("## Vincoli")
            for c in context.constraints:
                parts.append(f"- {c}")

        parts.extend([
            "",
            "## Istruzioni",
            "1. Analizza il codice esistente",
            "2. Implementa le modifiche necessarie",
            "3. Assicurati che il codice compili/funzioni",
            "4. Quando hai finito, esegui un test per verificare che funziona.",
        ])

        return "\n".join(parts)
