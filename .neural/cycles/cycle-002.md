# Cycle 2 — Goal: goal_002

## Istruzioni inviate a Claude Code

```
Sei nel progetto Neural-Hub.

Per implementare il goal **CI/CD Pipeline Setup**, seguirai le istruzioni seguenti:

**Step 1: Creazione del file di configurazione del pipeline**

* Crea un nuovo file chiamato `.github/workflows/cicd.yml` nella root del tuo repository.
* Inserisci il seguente codice nel file:
```yaml
name: CI/CD Pipeline

on:
  push:
    branches:
      - main

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v2
      - name: Install dependencies
        run: |
          npm install
      - name: Build and deploy
        run: |
          npm run build && npm run deploy
```
Questo file di configurazione definisce un pipeline che viene eseguito ogni volta che si effettua un push sul branch `main` del repository.

**Step 2: Configurazione del file di progetto**

* Apri il file `config/settings.py` e aggiungi le seguenti linee di codice:
```python
import os

CI_PIPELINE_URL = os.environ.get('CI_PIPELINE_URL')
```
Questo codice configura l'ambiente di esecuzione del pipeline e consente di accedere alle variabili ambiente.

**Step 3: Creazione del file di deploy**

* Crea un nuovo file chiamato `deploy.sh` nella cartella `scripts` del tuo repository.
* Inserisci il seguente codice nel file:
```bash
#!/bin/bash

# Configurazione del servizio di deploy
SERVICE_NAME="neural-hub"
DEPLOYMENT_URL="https://your-deployment-url.com"

# Esecuzione della build e del deploy
npm run build && npm run deploy
```
Questo file di deploy esegue la build e il deploy del progetto utilizzando le configurazioni definite nel file `config/settings.py`.

**Step 4: Aggiornamento del file di requirements**

* Apri il file `requirements.txt` e aggiungi le seguenti linee di codice:
```
github-actions/actions/checkout@v2
```
Questo aggiorna le dipendenze del progetto per includere l'azione GitHub Actions.

**Step 5: Esecuzione del pipeline**

* Apri la sezione "Actions" del tuo repository e clicca sul pulsante "Run workflow" accanto al file `.github/workflows/cicd.yml`.
* Scegli il branch `main` e fai clic su "Start workflow".

Quando hai finito, esegui un test per verificare che funziona.
```

## Output Claude Code

```
Serve approvazione per modificare i file. Ecco tutto il contenuto da creare/modificare:

---

**1. `.github/workflows/cicd.yml`** — adattato per Python (non npm):

```yaml
name: CI/CD Pipeline

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        run: python -m pytest tests/ -v

  deploy:
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Deploy
        env:
          CI_PIPELINE_URL: ${{ secrets.CI_PIPELINE_URL }}
        run: bash scripts/deploy.sh
```

---

**2. `config/settings.py`** — aggiungi prima di `# Server`:

```python
    # CI/CD
    ci_pipeline_url: str = ""
```

L'env var corrispondente sarà `NEURAL_HUB_CI_PIPELINE_URL` (grazie al `env_prefix` già configurato).

---

**3. `scripts/deploy.sh`** (nuovo file):

```bash
#!/bin/bash
set -euo pipefail

SERVICE_NAME="neural-hub"
DEPLOYMENT_URL="${CI_PIPELINE_URL:-}"

echo "Deploying $SERVICE_NAME..."

# Avvia/riavvia il server FastAPI
# Adatta questo comando al tuo ambiente di produzione
uvicorn main:app --host 0.0.0.0 --port 8400 &

echo "Deploy completato: $DEPLOYMENT_URL"
```

---

**Note importanti vs. le istruzioni originali:**
- Ho usato `actions/checkout@v4` e `setup-python@v5` (versioni attuali, non deprecate `@v2`)
- Rimosso `npm install/build/deploy` — questo progetto è Python puro
- **Non** ho aggiunto `github-actions/actions/checkout@v2` a `requirements.txt` — non ha senso per Python (è una GitHub Action, non un pacchetto pip)
- `ci_pipeline_url` si integra con il pattern `pydantic_settings.BaseSettings` già esistente

Per procedere, approva le modifiche ai file oppure esegui tu stesso i comandi terminale per creare la directory `.github/workflows`.

```

## Risultato

- Exit code: 0
- Durata: 102s
- Successo: Si
