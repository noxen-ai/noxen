"""API Routes: Terminale integrato via WebSocket.

Fornisce un terminale interattivo nel browser tramite WebSocket.
Ogni connessione WebSocket crea un processo PTY (pseudo-terminal)
che mantiene stato, working directory e environment.

Sicurezza: solo localhost, nessuna autenticazione esterna.
Pensato per uso locale su macchina dello sviluppatore.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import select
import signal
import struct
import termios
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger("noxen.terminal")

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

# Tiene traccia dei processi PTY attivi
_active_sessions: dict[str, dict] = {}


class ResizeRequest(BaseModel):
    session_id: str
    rows: int
    cols: int


class ExecRequest(BaseModel):
    command: str
    cwd: str | None = None
    timeout: int = 30


# ── WebSocket Terminal ────────────────────────────────────────────────

@router.websocket("/ws")
async def terminal_ws(websocket: WebSocket):
    """WebSocket per terminale interattivo con PTY reale."""
    await websocket.accept()

    # Crea un PTY (pseudo-terminal)
    master_fd, slave_fd = pty.openpty()

    # Configura dimensioni iniziali (80x24)
    winsize = struct.pack("HHHH", 24, 80, 0, 0)
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    # Avvia shell nel PTY
    shell = os.environ.get("SHELL", "/bin/zsh")
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["LANG"] = "en_US.UTF-8"

    pid = os.fork()
    if pid == 0:
        # Processo figlio — diventa la shell
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(slave_fd)
        os.chdir(str(Path.home() / "Neural-Hub"))
        os.execvpe(shell, [shell, "-l"], env)

    # Processo padre — gestisce I/O
    os.close(slave_fd)
    session_id = str(id(websocket))
    _active_sessions[session_id] = {"pid": pid, "fd": master_fd}

    # Set master_fd non-bloccante
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # Task per leggere output dal PTY e inviarlo al WebSocket
    # Usa un asyncio.Queue + loop.add_reader per evitare problemi con select/executor
    pty_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _on_pty_readable():
        """Callback invocata dal loop quando master_fd ha dati."""
        try:
            data = os.read(master_fd, 16384)
            if data:
                pty_queue.put_nowait(data)
            else:
                # EOF
                pty_queue.put_nowait(None)
        except OSError as e:
            import errno
            if e.errno == errno.EIO:
                # PTY chiuso (processo terminato)
                pty_queue.put_nowait(None)
            # EAGAIN: no data yet, ignora
            elif e.errno != errno.EAGAIN:
                pty_queue.put_nowait(None)

    loop.add_reader(master_fd, _on_pty_readable)

    async def read_pty():
        try:
            while True:
                data = await pty_queue.get()
                if data is None:
                    break
                await websocket.send_text(data.decode("utf-8", errors="replace"))
        except (asyncio.CancelledError, Exception):
            pass

    read_task = asyncio.create_task(read_pty())

    try:
        while True:
            msg = await websocket.receive_text()

            # Comandi di controllo JSON
            if msg.startswith('{"'):
                import json
                try:
                    cmd = json.loads(msg)
                    if cmd.get("type") == "resize":
                        rows = cmd.get("rows", 24)
                        cols = cmd.get("cols", 80)
                        winsize = struct.pack("HHHH", rows, cols, 0, 0)
                        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                        os.kill(pid, signal.SIGWINCH)
                        continue
                except (json.JSONDecodeError, KeyError):
                    pass

            # Input utente → scrivi nel PTY
            os.write(master_fd, msg.encode("utf-8"))

    except WebSocketDisconnect:
        logger.info(f"Terminale disconnesso: {session_id}")
    except Exception as e:
        logger.warning(f"Errore terminale: {e}")
    finally:
        read_task.cancel()
        try:
            loop.remove_reader(master_fd)
        except Exception:
            pass
        try:
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        _active_sessions.pop(session_id, None)


# ── HTTP API (per comandi singoli senza WebSocket) ────────────────────

@router.post("/exec")
async def exec_command(req: ExecRequest):
    """Esegui un singolo comando e restituisci l'output.

    Utile per integrazioni che non supportano WebSocket.
    """
    cwd = req.cwd or str(Path.home() / "Neural-Hub")

    try:
        proc = await asyncio.create_subprocess_shell(
            req.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=req.timeout
        )
        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        proc.kill()
        return {"exit_code": -1, "stdout": "", "stderr": "Timeout raggiunto"}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}


@router.get("/sessions")
async def list_sessions():
    """Lista sessioni terminale attive."""
    return {
        "active": len(_active_sessions),
        "sessions": [
            {"id": sid, "pid": info["pid"]}
            for sid, info in _active_sessions.items()
        ],
    }
