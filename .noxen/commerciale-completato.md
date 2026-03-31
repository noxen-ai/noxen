# Noxen v0.3.0 — Modello Commerciale Completato

**Data completamento:** 2026-03-31
**Test count finale:** 1193 passed, 0 failed

## Pre-push check output

```
=== NOXEN PRE-PUSH CHECK ===
OK   No API keys
OK   Rename complete
OK   No .env files
OK   No DB files
OK   LICENSE exists
OK   .env.example exists
Running tests... 1193 passed, 20 warnings
ALL CHECKS PASSED. Ready to push to GitHub.
```

## File creati/modificati in questo step

### RENAME
- Bulk sed su 168 file (11 pattern)
- `config/settings.py` — env_prefix NOXEN_
- `ui/static/js/app.js` — noxenApp()
- `ui/templates/dashboard.html` — x-data="noxenApp()"
- `main.py` — version 0.3.0

### STEP 1 — License files
- `LICENSE` — BSL 1.1
- `NOTICE` — Copyright
- SPDX headers su 8 core files

### STEP 2 — License model
- `core/tenants/model.py` — NoxenPlan, NOXEN_PLANS, TenantLicense, TenantLimitError, LicenseError

### STEP 3 — Repository
- `core/tenants/repository.py` — tabelle licenses + activated_projects, 6 metodi

### STEP 4 — Enforcement
- `core/execution/engine.py` — license check in run()
- `core/research_agent.py` — license check in research()
- `core/tenants/repository.py` — on-premise single tenant in create()
- `api/routes/admin.py` — HTTPException 403/402

### STEP 5 — Docker
- `Dockerfile`
- `docker-compose.yml`
- `.env.example`

### STEP 6 — Admin API + Dashboard
- `api/routes/admin.py` — 5 nuovi endpoint license
- `api/routes/license.py` — endpoint pubblico GET /api/tenants/license
- `ui/static/js/app.js` — licenseInfo state
- `ui/static/js/components/overview.js` — loadLicense()
- `ui/static/js/components/admin.js` — loadLicense(), upgradeLicense()
- `ui/templates/dashboard.html` — license badge header

### STEP 7 — Onboarding
- `scripts/onboard_client.py`

### STEP 8 — Tests
- `tests/test_licensing.py` — 31 test

### Docs
- `README.md`
- `CONTRIBUTING.md`
- `scripts/pre_push_check.sh`

## Conferma

Ready per GitHub push. Tutti i check passano.
