# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Noxen. See LICENSE for details.
#!/usr/bin/env python3
"""Noxen CLI.

Usage:
  noxen init <project-path>  — Scansiona, indicizza e connetti DB
  noxen start                — Avvia il server (porta 8400)
  noxen status               — Mostra stato orchestratore
  noxen query "domanda"      — Query rapida da terminale
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
BASE_URL = "http://localhost:8400"


def main():
    parser = argparse.ArgumentParser(
        prog="noxen",
        description="Noxen - Local AI Orchestrator",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Inizializza su un progetto")
    p_init.add_argument("project_path", help="Path del progetto da analizzare")

    # start
    sub.add_parser("start", help="Avvia il server Noxen")

    # status
    sub.add_parser("status", help="Mostra stato dell'orchestratore")

    # query
    p_query = sub.add_parser("query", help="Query rapida")
    p_query.add_argument("question", help="La domanda")
    p_query.add_argument("--service", default="", help="Microservizio specifico")
    p_query.add_argument("--board", action="store_true", help="Modalita' board (CDA)")

    # auth (device auth flow)
    sub.add_parser("auth", help="Authenticate with noxen.ai (device auth flow)")

    # license
    sub.add_parser("license", help="Show current license status")

    # tui
    p_tui = sub.add_parser("tui", help="Avvia interfaccia terminale (TUI)")
    p_tui.add_argument(
        "--url",
        default="http://localhost:8400",
        help="URL del server Noxen",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "start":
        cmd_start()
    elif args.command == "init":
        asyncio.run(cmd_init(args.project_path))
    elif args.command == "status":
        asyncio.run(cmd_status())
    elif args.command == "query":
        asyncio.run(cmd_query(args.question, args.service, args.board))
    elif args.command == "auth":
        asyncio.run(cmd_auth())
    elif args.command == "license":
        asyncio.run(cmd_license_status())
    elif args.command == "tui":
        cmd_tui(args.url)


def cmd_start():
    """Avvia il server."""
    console.print(Panel.fit(
        "[bold cyan]Noxen[/] v0.1.0\n"
        f"Server: {BASE_URL}\n"
        "Dashboard: apri nel browser",
        title="Starting",
    ))
    import uvicorn
    from config import settings
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        reload_dirs=[str(settings.hub_root)],
        reload_excludes=["skills/*", "data/*", "*.pyc", "__pycache__"],
    )


async def cmd_init(project_path: str):
    """Inizializza l'orchestratore."""
    path = Path(project_path).expanduser().resolve()
    if not path.is_dir():
        console.print(f"[red]Errore: {path} non e' una directory[/]")
        return

    console.print(Panel.fit(
        f"[bold cyan]Noxen Init[/]\n"
        f"Progetto: {path}",
        title="Inizializzazione",
    ))

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            console.print("[yellow]Scansione e indicizzazione in corso...[/]")
            resp = await client.post(
                f"{BASE_URL}/api/orchestrator/init",
                json={"project_path": str(path)},
            )
            resp.raise_for_status()
            data = resp.json()

        # Mostra risultati
        table = Table(title="Risultati Init")
        table.add_column("Componente", style="cyan")
        table.add_column("Stato", style="green")

        discovery = data.get("discovery", {})
        table.add_row("Microservizi", str(discovery.get("services", 0)))
        table.add_row("Linguaggi", ", ".join(discovery.get("languages", [])))
        table.add_row("Framework", ", ".join(discovery.get("frameworks", [])))

        db = data.get("database", {})
        table.add_row(
            "Database",
            f"{'Connesso' if db.get('connected') else 'Non connesso'} "
            f"({db.get('tables', 0)} tabelle)"
        )

        idx = data.get("indexing", {})
        table.add_row("Indicizzazione", f"{idx.get('services_queued', 0)} servizi in coda")

        sk = data.get("skills", {})
        table.add_row("Skills Claude", str(sk.get("available", 0)))

        console.print(table)
        console.print("\n[green]Init completato! Apri http://localhost:8400 per la dashboard.[/]")

    except httpx.ConnectError:
        console.print("[red]Server non raggiungibile. Esegui prima: noxen start[/]")
    except Exception as e:
        console.print(f"[red]Errore: {e}[/]")


async def cmd_status():
    """Mostra stato."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BASE_URL}/api/orchestrator/status")
            data = resp.json()

        table = Table(title="Noxen Status")
        table.add_column("", style="cyan")
        table.add_column("Valore", style="white")

        table.add_row("Inizializzato", "Si" if data.get("initialized") else "No")
        table.add_row("Progetto", data.get("project_path", "-"))
        table.add_row("Servizi", str(data.get("total_services", 0)))
        table.add_row("Linguaggi", ", ".join(data.get("languages", [])))
        table.add_row("Framework", ", ".join(data.get("frameworks", [])))
        table.add_row("DB Connesso", "Si" if data.get("db_connected") else "No")
        table.add_row("Tabelle DB", str(data.get("db_tables", 0)))
        table.add_row("Skills", str(data.get("available_skills", 0)))
        table.add_row("LLM Provider", data.get("active_provider", "-"))
        table.add_row("Modalita'", data.get("llm_mode", "-"))
        table.add_row("Provider Attivi", ", ".join(data.get("available_providers", [])))

        console.print(table)

    except httpx.ConnectError:
        console.print("[red]Server non raggiungibile. Esegui prima: noxen start[/]")
    except Exception as e:
        console.print(f"[red]Errore: {e}[/]")


async def cmd_query(question: str, service: str, board: bool):
    """Query rapida."""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{BASE_URL}/api/orchestrator/query",
                json={
                    "question": question,
                    "service": service,
                    "mode": "board" if board else "single",
                },
            )
            data = resp.json()

        if data.get("mode") == "board":
            # Mostra tutte le risposte
            for r in data.get("responses", []):
                if r.get("content"):
                    console.print(Panel(
                        r["content"],
                        title=f"[bold]{r['provider']}[/] ({r['model']})",
                        subtitle=f"{r['latency_ms']}ms",
                    ))

            console.print(Panel(
                data.get("synthesis", ""),
                title=f"[bold green]SINTESI ({data.get('chairman', '')})[/]",
                subtitle=f"Consenso: {data.get('consensus', '')} | {data.get('latency_ms', 0)}ms",
            ))
        else:
            console.print(Panel(
                data.get("content", data.get("error", "Nessuna risposta")),
                title=f"[bold]{data.get('provider', '')}[/] ({data.get('model', '')})",
                subtitle=f"{data.get('latency_ms', 0)}ms",
            ))

    except httpx.ConnectError:
        console.print("[red]Server non raggiungibile. Esegui prima: noxen start[/]")
    except Exception as e:
        console.print(f"[red]Errore: {e}[/]")


# ── Device Auth Flow ──────────────────────────────────────────────────


async def device_auth_flow(
    server_url: str,
    timeout_s: int = 300,
    poll_interval_s: int = 5,
) -> str:
    """OAuth Device Flow verso api.noxen.ai. Ritorna license key."""
    import webbrowser
    import time

    # Step 1: richiedi device code
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{server_url}/v1/auth/device",
            json={"client": "noxen-cli", "version": "0.3.0"},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_url = data["verification_url"]
    expires_in = data.get("expires_in", 300)
    interval = data.get("interval", poll_interval_s)

    # Step 2: apri browser
    print(f"\nOpening {verification_url} ...")
    print(f"If browser does not open, visit:")
    print(f"  {verification_url}")
    print(f"  Enter code: {user_code}\n")

    try:
        webbrowser.open(f"{verification_url}?code={user_code}")
    except Exception:
        pass

    # Step 3: polling
    print("Waiting for authentication...", end="", flush=True)
    import time as _time
    deadline = _time.time() + expires_in

    async with httpx.AsyncClient() as client:
        while _time.time() < deadline:
            await asyncio.sleep(interval)
            print(".", end="", flush=True)

            try:
                r = await client.post(
                    f"{server_url}/v1/auth/device/token",
                    json={"device_code": device_code},
                    timeout=10.0,
                )
                data = r.json()
                status = data.get("status")

                if status == "authorized":
                    print()
                    return data["license_key"]
                elif status == "pending":
                    continue
                elif status == "expired":
                    raise Exception("Code expired. Run noxen auth again.")
                elif status == "denied":
                    raise Exception("Authentication denied.")
            except httpx.HTTPStatusError:
                continue

    raise Exception("Authentication timeout. Run noxen auth again.")


def save_license_key(key: str, env_file: str = ".env") -> None:
    """Salva license key nel .env."""
    env_path = Path(env_file)

    if env_path.exists():
        content = env_path.read_text()
        if "NOXEN_LICENSE_KEY" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("NOXEN_LICENSE_KEY"):
                    new_lines.append(f"NOXEN_LICENSE_KEY={key}")
                else:
                    new_lines.append(line)
            env_path.write_text("\n".join(new_lines) + "\n")
        else:
            with env_path.open("a") as f:
                f.write(f"\nNOXEN_LICENSE_KEY={key}\n")
    else:
        env_path.write_text(f"NOXEN_LICENSE_KEY={key}\n")


async def cmd_auth():
    """Authenticate with noxen.ai using device auth flow."""
    from config.settings import settings

    print("\nWelcome to Noxen v0.3.0")
    print("=" * 40)

    if settings.noxen_license_key:
        print(
            f"Already authenticated.\n"
            f"License key present in configuration.\n"
            f"Run 'noxen license' to check license status."
        )
        return

    print("\nAuthentication required.")
    print("Press Enter to open noxen.ai in your browser...")
    input()

    try:
        key = await device_auth_flow(server_url=settings.license_server_url)
        save_license_key(key)

        print(f"\n\u2713 Authenticated successfully")
        print(f"\u2713 License key saved to .env")
        print(f"\nNow run: docker-compose up -d")
        print(f"Then open: http://localhost:8400")

    except KeyboardInterrupt:
        print("\n\nCancelled.")
    except Exception as e:
        print(f"\n\u2717 Authentication failed: {e}")
        print("For manual setup visit: https://noxen.ai/dashboard")


async def cmd_license_status():
    """Show current license status."""
    from config.settings import settings

    if not settings.noxen_license_key:
        print("Not authenticated. Run: noxen auth")
        return

    print(f"License key: {settings.noxen_license_key[:12]}...")

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{settings.license_server_url}/v1/license/validate",
                json={"key": settings.noxen_license_key, "version": "0.3.0"},
                timeout=10.0,
            )
            data = r.json()

        if data.get("valid"):
            plan = data.get("plan", "unknown")
            expires = data.get("expires_at", "")[:10]
            print(f"Plan:    {plan}")
            print(f"Expires: {expires}")
            print(f"Status:  \u2713 Active")
        else:
            print(f"Status:  \u2717 Invalid")
            print(f"Visit:   https://noxen.ai/dashboard")

    except Exception:
        print("Status:  \u26a0 Could not reach license server")
        print(f"Grace period: {settings.license_grace_period_days} days")


def cmd_tui(url: str):
    """Avvia la TUI Textual."""
    console.print(Panel.fit(
        "[bold cyan]Noxen TUI[/]\n"
        f"Server: {url}\n"
        "Keys: 1-7 tabs | r refresh | q quit",
        title="Terminal UI",
    ))
    from tui.app import NoxenTUI
    app = NoxenTUI(api_base_url=url)
    app.run()


if __name__ == "__main__":
    main()
