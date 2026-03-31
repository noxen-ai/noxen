# Cycle 3 — Goal: goal_004

## Istruzioni inviate a Claude Code

```
Sei nel progetto Neural-Hub.

Per implementare la sicurezza degli endpoint API, seguirai queste istruzioni precise e concrete:

**Passo 1: Installa Auth0**

* Apri il file `requirements.txt` e aggiungi la seguente riga:
```
auth0=2.13.0
```
* Esegui il comando `pip install -r requirements.txt` per installare Auth0.

**Passo 2: Configura Auth0**

* Crea un nuovo file chiamato `api/middleware/auth.py` con il seguente contenuto:
```python
import os
from auth0 import Auth0

auth0_client_id = os.environ['AUTH0_CLIENT_ID']
auth0_domain = os.environ['AUTH0_DOMAIN']

auth0 = Auth0(client_id=auth0_client_id, domain=auth0_domain)
```
* Configura le variabili ambiente `AUTH0_CLIENT_ID` e `AUTH0_DOMAIN` nel file `.env`.

**Passo 3: Aggiungi middleware per la sicurezza**

* Apri il file `api/middleware/index.py` e aggiungi il seguente codice:
```python
from auth0 import Auth0
from flask import request, jsonify

def authenticate_api(request):
    if not request.headers.get('Authorization'):
        return jsonify({'error': 'Unauthorized'}), 401
    token = request.headers['Authorization'].split()[1]
    user_id = auth0.decode_token(token)['sub']
    return {'user_id': user_id}

app = Flask(__name__)
app.before_request(authenticate_api)
```
* Aggiungi il middleware `authenticate_api` all'inizio della pipeline di trattamento delle richieste API.

**Passo 4: Aggiorna gli endpoint API**

* Apri il file `api/routes.py` e aggiorna gli endpoint API per utilizzare il middleware `authenticate_api`. Ad esempio, se hai un endpoint `/users`, aggiorna la funzione come segue:
```python
from api.middleware import authenticate_api

@app.route('/users', methods=['GET'])
def get_users():
    user_id = request.headers.get('user_id')
    # Resto del codice
```
* Ripeti questo passaggio per tutti gli endpoint API.

Quando hai finito, esegui un test per verificare che funziona.
```

## Output Claude Code

```
L'utente ha negato la scrittura. Prima di procedere devo chiarire l'approccio, dato che le istruzioni originali hanno problemi fondamentali.

Ecco il piano corretto adattato al progetto reale (FastAPI):

---

**Correzioni necessarie rispetto alle istruzioni originali:**

| Istruzione originale | Problema | Correzione |
|---|---|---|
| `auth0=2.13.0` | Package inesistente | `python-jose[cryptography]==3.3.0` |
| `from auth0 import Auth0` + `Flask` | Codice Flask, non FastAPI | FastAPI `Depends()` |
| `auth0.decode_token()` | Metodo inesistente | Verifica JWKS manuale |
| `app.before_request(...)` | API Flask | `app.middleware("http")` o `Depends` per-route |

**Struttura corretta per FastAPI:**

```python
# api/middleware/auth.py
import os
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
import httpx

AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN")
AUTH0_AUDIENCE = os.environ.get("AUTH0_AUDIENCE")

bearer = HTTPBearer()

async def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer)
) -> dict:
    token = credentials.credentials
    # Fetch JWKS from Auth0
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json")
        jwks = r.json()
    # Verifica e decodifica il JWT
    try:
        payload = jwt.decode(token, jwks, algorithms=["RS256"], audience=AUTH0_AUDIENCE)
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=str(e))
```

**Uso per-route** (non global, per non bloccare `/api/health` e la dashboard):
```python
# In qualsiasi route
from api.middleware.auth import verify_token

@router.get("/api/users")
async def get_users(user: dict = Depends(verify_token)):
    return {"user_id": user["sub"]}
```

---

Vuoi che proceda con questa implementazione corretta? Considera anche che Neural-Hub sembra un tool **locale** (usa Ollama locale, ChromaDB locale) — ha senso richiedere Auth0 su tutti gli endpoint, o preferisci proteggere solo un sottoinsieme?

```

## Risultato

- Exit code: 0
- Durata: 66s
- Successo: Si
