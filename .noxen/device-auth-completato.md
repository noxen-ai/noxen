# Device Auth Flow — Completato

Data: 2026-03-31

## Cosa e' stato implementato

### TASK A: Settings
- `noxen_license_key`, `license_server_url`, `license_grace_period_days` in config/settings.py

### TASK B: CLI Device Auth Flow
- `noxen auth` — OAuth Device Flow (browser + polling)
- `noxen license` — mostra stato licenza
- `device_auth_flow()` — POST /v1/auth/device -> browser -> poll /v1/auth/device/token
- `save_license_key()` — salva/aggiorna NOXEN_LICENSE_KEY nel .env
- `cmd_auth()`, `cmd_license_status()` — comandi CLI

### TASK C: Bootstrap License Check
- `_check_license_key()` in core/bootstrap.py (required=False)
- Validazione vs server con cache locale (grace period)
- Cache in data/.license_cache.json
- Grace period configurabile (default 7 giorni)

### TASK D: .gitignore
- Creato .gitignore con data/.license_cache.json escluso

### TASK E: Test
- tests/test_device_auth.py — 15 test
  - 8 test _check_license_key (no key, valid, invalid, unreachable, cache, expired cache, cache creation, required=False)
  - 3 test save_license_key (create, append, replace)
  - 2 test device_auth_flow (success, denied)
  - 2 test bootstrap run integration (license in results, missing doesn't block)

## Conteggio check bootstrap
- 10 check totali: internet, license_key, qdrant, embedding, data_dirs, default_tenant, claude_cli, github_token, exa_key, firecrawl_key

## Test totali
- 1213 passed (pre_push_check.sh)
