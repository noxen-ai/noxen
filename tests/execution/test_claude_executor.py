"""Test suite per core/execution/claude_executor.py — Step 4.3."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from core.execution.claude_executor import (
    ClaudeExecutor,
    ExecutionResult,
    InstructionContext,
    CLAUDE_TIMEOUT_S,
    MAX_OUTPUT_CHARS,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def executor():
    """ClaudeExecutor senza LLM."""
    return ClaudeExecutor(llm_query_fn=None, timeout_s=30)


@pytest.fixture
def llm_executor():
    """ClaudeExecutor con LLM mock."""
    mock_llm = AsyncMock(return_value="LLM generated instructions for the task")
    return ClaudeExecutor(llm_query_fn=mock_llm, timeout_s=30)


@pytest.fixture
def sample_context():
    """InstructionContext di esempio."""
    return InstructionContext(
        project_name="MyApp",
        project_path="/tmp/myapp",
        goal_title="Add error handling",
        goal_description="Implementa error handling consistente in tutti gli endpoint API.",
        goal_category="fix",
    )


@pytest.fixture
def context_with_extras():
    """InstructionContext con contesto e vincoli."""
    return InstructionContext(
        project_name="MyApp",
        project_path="/tmp/myapp",
        goal_title="Add caching",
        goal_description="Aggiungi caching Redis per le query frequenti.",
        goal_category="optimization",
        accumulated_context="Previous cycle found N+1 queries in user endpoint.",
        constraints=["Non modificare le API pubbliche", "Mantenere backward compat"],
    )


# ── Test ExecutionResult ─────────────────────────────────────────────

def test_execution_result_creation():
    """ExecutionResult si crea con valori corretti."""
    r = ExecutionResult(
        goal_id="g1",
        instructions="do something",
        output="done",
        exit_code=0,
        duration_s=5.0,
    )
    assert r.goal_id == "g1"
    assert r.success is False  # default
    assert r.error == ""
    assert r.files_changed == []
    assert r.verification == ""


def test_execution_result_to_dict():
    """to_dict() produce dizionario completo."""
    r = ExecutionResult(
        goal_id="g1", instructions="x", output="y",
        exit_code=0, duration_s=1.0, success=True,
        files_changed=["a.py"],
    )
    d = r.to_dict()
    assert d["goal_id"] == "g1"
    assert d["success"] is True
    assert d["files_changed"] == ["a.py"]


# ── Test InstructionContext ──────────────────────────────────────────

def test_instruction_context_creation(sample_context):
    """InstructionContext si crea correttamente."""
    assert sample_context.project_name == "MyApp"
    assert sample_context.goal_title == "Add error handling"
    assert sample_context.accumulated_context == ""
    assert sample_context.constraints == []


def test_instruction_context_with_extras(context_with_extras):
    """InstructionContext con contesto e vincoli."""
    assert context_with_extras.accumulated_context != ""
    assert len(context_with_extras.constraints) == 2


# ── Test generate_instructions (template) ────────────────────────────

@pytest.mark.asyncio
async def test_generate_template_instructions(executor, sample_context):
    """Senza LLM, genera istruzioni template-based."""
    instructions = await executor.generate_instructions(sample_context)
    assert "Sei nel progetto MyApp" in instructions
    assert "Add error handling" in instructions
    assert "fix" in instructions


@pytest.mark.asyncio
async def test_generate_template_with_constraints(executor, context_with_extras):
    """Template include vincoli."""
    instructions = await executor.generate_instructions(context_with_extras)
    assert "Vincoli" in instructions
    assert "backward compat" in instructions


@pytest.mark.asyncio
async def test_generate_template_has_verification(executor, sample_context):
    """Template include istruzione di verifica."""
    instructions = await executor.generate_instructions(sample_context)
    assert "verificare" in instructions.lower() or "test" in instructions.lower()


# ── Test generate_instructions (LLM) ────────────────────────────────

@pytest.mark.asyncio
async def test_generate_llm_instructions(llm_executor, sample_context):
    """Con LLM, genera istruzioni via LLM."""
    instructions = await llm_executor.generate_instructions(sample_context)
    assert "LLM generated" in instructions
    llm_executor._llm_query.assert_called_once()


@pytest.mark.asyncio
async def test_generate_llm_fallback_on_error(sample_context):
    """Se LLM fallisce, fallback a template."""
    failing_llm = AsyncMock(side_effect=Exception("LLM unavailable"))
    executor = ClaudeExecutor(llm_query_fn=failing_llm)
    instructions = await executor.generate_instructions(sample_context)
    # Should fallback to template
    assert "Sei nel progetto MyApp" in instructions


@pytest.mark.asyncio
async def test_generate_llm_passes_context(context_with_extras):
    """LLM riceve contesto accumulato e vincoli."""
    mock_llm = AsyncMock(return_value="instructions with context")
    executor = ClaudeExecutor(llm_query_fn=mock_llm)
    await executor.generate_instructions(context_with_extras)

    call_args = mock_llm.call_args
    system_msg = call_args[0][0]
    assert "Previous cycle" in system_msg or "CONTESTO" in system_msg


# ── Test execute ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_success(executor, tmp_path):
    """execute() con mock subprocess successo."""
    # Setup git in tmp_path
    proc = await asyncio.create_subprocess_exec(
        "git", "init",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(tmp_path),
    )
    await proc.communicate()

    with patch.object(executor, "_run_claude_cli", new_callable=AsyncMock) as mock_cli:
        mock_cli.return_value = ("Task completed successfully. All files have been created and tests pass correctly.", 0)
        result = await executor.execute(
            instructions="Do something",
            working_dir=str(tmp_path),
            goal_id="g1",
        )

    assert result.exit_code == 0
    assert result.success is True
    assert "Task completed" in result.output
    assert result.goal_id == "g1"
    assert result.duration_s > 0


@pytest.mark.asyncio
async def test_execute_failure(executor, tmp_path):
    """execute() con exit code non-zero."""
    with patch.object(executor, "_run_claude_cli", new_callable=AsyncMock) as mock_cli:
        mock_cli.return_value = ("Error occurred", 1)
        result = await executor.execute(
            instructions="Do something",
            working_dir=str(tmp_path),
            goal_id="g1",
        )

    assert result.exit_code == 1
    assert result.success is False


@pytest.mark.asyncio
async def test_execute_timeout(executor, tmp_path):
    """execute() gestisce timeout."""
    with patch.object(executor, "_run_claude_cli", new_callable=AsyncMock) as mock_cli:
        mock_cli.side_effect = asyncio.TimeoutError()
        result = await executor.execute(
            instructions="Long task",
            working_dir=str(tmp_path),
            goal_id="g1",
        )

    assert result.exit_code == -1
    assert "Timeout" in result.error


@pytest.mark.asyncio
async def test_execute_cli_not_found(executor, tmp_path):
    """execute() gestisce Claude CLI non trovato."""
    with patch.object(executor, "_run_claude_cli", new_callable=AsyncMock) as mock_cli:
        mock_cli.side_effect = FileNotFoundError("claude not found")
        result = await executor.execute(
            instructions="Task",
            working_dir=str(tmp_path),
            goal_id="g1",
        )

    assert result.exit_code == -1
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_execute_generic_error(executor, tmp_path):
    """execute() gestisce errori generici."""
    with patch.object(executor, "_run_claude_cli", new_callable=AsyncMock) as mock_cli:
        mock_cli.side_effect = RuntimeError("unexpected error")
        result = await executor.execute(
            instructions="Task",
            working_dir=str(tmp_path),
            goal_id="g1",
        )

    assert result.exit_code == -1
    assert "unexpected error" in result.error


@pytest.mark.asyncio
async def test_execute_truncates_output(executor, tmp_path):
    """execute() tronca output oltre MAX_OUTPUT_CHARS."""
    long_output = "x" * (MAX_OUTPUT_CHARS + 1000)
    with patch.object(executor, "_run_claude_cli", new_callable=AsyncMock) as mock_cli:
        mock_cli.return_value = (long_output, 0)
        result = await executor.execute(
            instructions="Task",
            working_dir=str(tmp_path),
            goal_id="g1",
        )

    assert len(result.output) == MAX_OUTPUT_CHARS


@pytest.mark.asyncio
async def test_execute_short_output_not_success(executor, tmp_path):
    """Output troppo corto (<50 chars) non e' success anche con exit 0."""
    with patch.object(executor, "_run_claude_cli", new_callable=AsyncMock) as mock_cli:
        mock_cli.return_value = ("ok", 0)  # Only 2 chars
        result = await executor.execute(
            instructions="Task",
            working_dir=str(tmp_path),
            goal_id="g1",
        )

    assert result.exit_code == 0
    assert result.success is False  # Too short


# ── Test verify ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_with_llm():
    """verify() chiama LLM e ritorna valutazione."""
    mock_llm = AsyncMock(return_value="SI, il goal e' stato completato. Qualita: 8/10.")
    executor = ClaudeExecutor(llm_query_fn=mock_llm)

    result = ExecutionResult(
        goal_id="g1", instructions="x", output="code written",
        exit_code=0, duration_s=5.0, files_changed=["a.py"],
    )

    verification = await executor.verify(result, "Add tests", "Write unit tests")
    assert "completato" in verification
    assert result.verification != ""


@pytest.mark.asyncio
async def test_verify_without_llm(executor):
    """verify() senza LLM ritorna stringa vuota."""
    result = ExecutionResult(
        goal_id="g1", instructions="x", output="y",
        exit_code=0, duration_s=1.0,
    )

    verification = await executor.verify(result, "Title", "Desc")
    assert verification == ""


@pytest.mark.asyncio
async def test_verify_llm_error():
    """verify() gestisce errore LLM gracefully."""
    mock_llm = AsyncMock(side_effect=Exception("LLM down"))
    executor = ClaudeExecutor(llm_query_fn=mock_llm)

    result = ExecutionResult(
        goal_id="g1", instructions="x", output="y",
        exit_code=0, duration_s=1.0,
    )

    verification = await executor.verify(result, "Title", "Desc")
    assert "error" in verification.lower()


# ── Test constants ───────────────────────────────────────────────────

def test_claude_timeout_constant():
    """CLAUDE_TIMEOUT_S ha valore sensato."""
    assert CLAUDE_TIMEOUT_S == 600  # 10 minutes


def test_max_output_chars_constant():
    """MAX_OUTPUT_CHARS ha valore sensato."""
    assert MAX_OUTPUT_CHARS == 50_000


# ── Test constructor ─────────────────────────────────────────────────

def test_executor_default_timeout():
    """Default timeout e' CLAUDE_TIMEOUT_S."""
    executor = ClaudeExecutor()
    assert executor._timeout == CLAUDE_TIMEOUT_S


def test_executor_custom_timeout():
    """Timeout custom viene usato."""
    executor = ClaudeExecutor(timeout_s=120)
    assert executor._timeout == 120


def test_executor_no_llm():
    """Executor senza LLM ha _llm_query None."""
    executor = ClaudeExecutor()
    assert executor._llm_query is None


def test_executor_with_llm():
    """Executor con LLM ha _llm_query impostata."""
    fn = AsyncMock()
    executor = ClaudeExecutor(llm_query_fn=fn)
    assert executor._llm_query is fn


# ── FIX 3: CLI availability checks ──────────────────────────────────

@pytest.mark.asyncio
async def test_check_availability_true():
    """check_availability() returns True when claude is in PATH."""
    executor = ClaudeExecutor()
    with patch("core.execution.claude_executor.shutil.which", return_value="/usr/local/bin/claude"):
        assert await executor.check_availability() is True


@pytest.mark.asyncio
async def test_check_availability_false():
    """check_availability() returns False when claude is not in PATH."""
    executor = ClaudeExecutor()
    with patch("core.execution.claude_executor.shutil.which", return_value=None):
        assert await executor.check_availability() is False


@pytest.mark.asyncio
async def test_execute_without_claude_returns_error(tmp_path):
    """execute() returns error result when claude CLI not available."""
    executor = ClaudeExecutor()
    with patch("core.execution.claude_executor.shutil.which", return_value=None):
        result = await executor.execute(
            instructions="Do something",
            working_dir=str(tmp_path),
            goal_id="g1",
        )

    assert result.success is False
    assert result.exit_code == -1
    assert "npm install" in result.error
    assert "claude-code" in result.error


@pytest.mark.asyncio
async def test_execute_with_claude_proceeds(executor, tmp_path):
    """execute() proceeds normally when claude CLI is available."""
    with patch("core.execution.claude_executor.shutil.which", return_value="/usr/bin/claude"):
        with patch.object(executor, "_run_claude_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.return_value = ("output ok", 0)
            with patch.object(executor, "_get_changed_files", new_callable=AsyncMock) as mock_files:
                mock_files.return_value = []
                result = await executor.execute(
                    instructions="Test task with sufficient output to pass",
                    working_dir=str(tmp_path),
                    goal_id="g1",
                )

    assert result.exit_code == 0
