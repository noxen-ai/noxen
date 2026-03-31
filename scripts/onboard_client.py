#!/usr/bin/env python3
"""Noxen — Client Onboarding Script.

Creates a tenant, upgrades its license, generates an API key,
and prints all credentials for the client.

Usage:
    python scripts/onboard_client.py \
        --name "Acme Corp" \
        --slug acme \
        --plan team \
        --reference INV-2026-001 \
        --admin-key your-admin-key
"""

import argparse
import asyncio
import os
import sys

try:
    import httpx
except ImportError:
    print("Errore: httpx non installato. Esegui: pip install httpx")
    sys.exit(1)


async def onboard(
    name: str,
    slug: str,
    plan: str,
    reference: str,
    notes: str,
    admin_key: str,
    server: str,
) -> None:
    headers = {
        "Authorization": f"Bearer {admin_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: Create tenant
        print(f"[1/3] Creazione tenant '{name}' ({slug})...")
        r = await client.post(
            f"{server}/api/admin/tenants",
            headers=headers,
            json={"name": name, "slug": slug, "plan": "enterprise"},
        )
        r.raise_for_status()
        data = r.json()
        tenant = data.get("tenant", data)
        tenant_id = tenant.get("id", slug)
        print(f"      Tenant creato: {tenant_id}")

        # Step 2: Upgrade license
        print(f"[2/3] Upgrade licenza a piano '{plan}'...")
        r = await client.post(
            f"{server}/api/admin/tenants/{tenant_id}/license/upgrade",
            headers=headers,
            json={
                "plan": plan,
                "purchase_reference": reference,
                "notes": notes,
            },
        )
        r.raise_for_status()
        lic = r.json()
        print(f"      Licenza attivata: {lic.get('plan_name', plan)}")

        # Step 3: Generate API key
        print(f"[3/3] Generazione API key...")
        r = await client.post(
            f"{server}/api/admin/tenants/{tenant_id}/api-keys",
            headers=headers,
            json={"key_name": "production"},
        )
        r.raise_for_status()
        key_data = r.json()
        api_key = key_data.get("api_key", "")

        # Output finale
        sep = "=" * 50
        print(f"\n{sep}")
        print("DATI CLIENTE — SALVA ORA")
        print(sep)
        print(f"Nome:      {name}")
        print(f"Tenant ID: {tenant_id}")
        print(f"API Key:   {api_key}")
        plan_display = lic.get("plan_display", lic.get("plan_name", plan))
        print(f"Piano:     {plan_display}")
        exp = lic.get("expires_at", "")
        exp_display = exp[:10] if exp else "mai"
        print(f"Scadenza:  {exp_display}")
        print(f"Rif.:      {reference}")
        print(sep)
        print("ATTENZIONE: la API key non viene mostrata di nuovo.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Onboard a Noxen client — crea tenant, licenza e API key."
    )
    parser.add_argument("--name", required=True, help="Nome azienda")
    parser.add_argument("--slug", required=True, help="Slug URL-safe")
    parser.add_argument(
        "--plan",
        default="team",
        choices=["trial", "starter", "team", "scale", "enterprise"],
        help="Piano commerciale (default: team)",
    )
    parser.add_argument(
        "--reference", required=True, help="Riferimento acquisto (es. INV-2026-001)"
    )
    parser.add_argument("--notes", default="", help="Note opzionali")
    parser.add_argument("--admin-key", default=None, help="Admin API key")
    parser.add_argument(
        "--server", default="http://localhost:8400", help="URL server Noxen"
    )
    args = parser.parse_args()

    key = args.admin_key or os.environ.get("NOXEN_ADMIN_API_KEY")
    if not key:
        print("Errore: --admin-key o NOXEN_ADMIN_API_KEY richiesto")
        sys.exit(1)

    asyncio.run(
        onboard(
            args.name,
            args.slug,
            args.plan,
            args.reference,
            args.notes,
            key,
            args.server,
        )
    )


if __name__ == "__main__":
    main()
