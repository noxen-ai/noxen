# Cycle 11 — Goal: goal_010

## Istruzioni inviate a Claude Code

```
Sei nel progetto Neural-Hub. Ecco le istruzioni per espandere il test suite:

**Step 1: Identify Testable Modules**
Open the `tests` folder and identify the modules that need testing, such as:
- `api` tests for API endpoints
- `core` tests for core logic and functionality
- `data` tests for data processing and validation

Create a new file named `test_api.py` in the `tests/api` directory to test API endpoints. For example:

```python
import pytest
from neural_hub.api import api_routes

def test_get_endpoint():
    response = api_routes.get('/api/v1/endpoint')
    assert response.status_code == 200

def test_post_endpoint():
    data = {'key': 'value'}
    response = api_routes.post('/api/v1/endpoint', json=data)
    assert response.status_code == 201
```

**Step 2: Implement Tests for Core Logic**
Create a new file named `test_core.py` in the `tests/core` directory to test core logic and functionality. For example:

```python
import pytest
from neural_hub.core import auto_discovery

def test_auto_discovery():
    result = auto_discovery.get_skills()
    assert len(result) > 0

def test_claude_skill_parser():
    skill_data = {'skill_name': 'Example Skill'}
    result = claude_skill_parser.parse(skill_data)
    assert result['name'] == 'Example Skill'
```

**Step 3: Implement Tests for Data Processing**
Create a new file named `test_data.py` in the `tests/data` directory to test data processing and validation. For example:

```python
import pytest
from neural_hub.data import chroma

def test_chroma_processing():
    data = {'key': 'value'}
    result = chroma.process(data)
    assert isinstance(result, dict)

def test_data_validation():
    data = {'invalid_key': None}
    with pytest.raises(ValueError):
        chroma.validate(data)
```

**Step 4: Run Tests**
Run the tests using a testing framework like Jest or RSpec. For example:

* Using Jest:
```bash
jest --config jest.config.js
```
* Using RSpec:
```bash
rspec spec/
```

Quando hai finito, esegui un test per verificare che funziona.
```

## Output Claude Code

```
Every operation is waiting for your explicit approval in the Claude Code permission dialog. To unblock this, you can either:

1. **Approve each prompt as it appears** in the Claude Code UI
2. **Add a blanket permission** by running `/update-config` to allow writes to the Neural-Hub directory

The simplest fix is to add `Write(/Users/luigi/Neural-Hub/**)` to your allowed permissions. Want me to use the update-config skill to do that?

Alternatively, if you just want to see the test code so you can create it yourself, here it is:

---

**`tests/__init__.py`** — empty

**`tests/api/__init__.py`** — empty

**`tests/api/test_api.py`:**
```python
"""Tests for API endpoints."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from api.routes import health


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(health.router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_health_returns_200(client):
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_response_body(client):
    response = client.get("/api/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "Neural Hub"
```

**`tests/core/__init__.py`** — empty

**`tests/core/test_core.py`:**
```python
"""Tests for core modules: AutoDiscovery and claude_skill_parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
import tempfile
import json
from core.auto_discovery import AutoDiscovery, ServiceInfo, EcosystemMap
from core.claude_skill_parser import (
    _parse_yaml_frontmatter,
    _extract_owner,
    parse_plugin_repo,
    ClaudeSkill,
    ClaudePlugin,
)


# ── AutoDiscovery ─────────────────────────────────────────────────────

class TestAutoDiscovery:
    def test_scan_empty_dir_returns_map(self, tmp_path):
        discovery = AutoDiscovery(tmp_path)
        result = discovery.scan()
        assert isinstance(result, EcosystemMap)
        assert result.root_path == str(tmp_path)

    def test_scan_detects_python_service(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        (tmp_path / "main.py").write_text("# entry\n")
        discovery = AutoDiscovery(tmp_path)
        result = discovery.scan()
        assert result.total_services >= 1
        assert "python" in result.languages

    def test_scan_detects_node_service(self, tmp_path):
        svc = tmp_path / "frontend"
        svc.mkdir()
        (svc / "package.json").write_text(json.dumps({"name": "app", "dependencies": {"react": "*"}}))
        discovery = AutoDiscovery(tmp_path)
        result = discovery.scan()
        assert any(s.language == "javascript" for s in result.services)

    def test_scan_detects_framework(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        discovery = AutoDiscovery(tmp_path)
        result = discovery.scan()
        python_services = [s for s in result.services if s.language == "python"]
        assert any(s.framework == "fastapi" for s in python_services)

    def test_save_map_creates_json(self, tmp_path):
        src = tmp_path / "project"
        src.mkdir()
        (src / "requirements.txt").write_text("flask\n")
        discovery = AutoDiscovery(src)
        out = discovery.save_map(tmp_path / "output")
        assert out.exists()
        data = json.loads(out.read_text())
        assert "services" in data

    def test_ignores_venv_and_node_modules(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "requirements.txt").write_text("pip\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "package.json").write_text("{}")
        discovery = AutoDiscovery(tmp_path)
        result = discovery.scan()
        service_names = [s.name for s in result.services]
        assert ".venv" not in service_names
        assert "node_modules" not in service_names


# ── claude_skill_parser ───────────────────────────────────────────────

class TestParseYamlFrontmatter:
    def test_parses_basic_fields(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: My Skill\ndescription: Does stuff\nversion: 2.0.0\n---\n# Body")
        result = _parse_yaml_frontmatter(f)
        assert result["name"] == "My Skill"
        assert result["description"] == "Does stuff"
        assert result["version"] == "2.0.0"

    def test_parses_list_field(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("---\ntags: [python, testing, ai]\n---\n")
        result = _parse_yaml_frontmatter(f)
        assert result["tags"] == ["python", "testing", "ai"]

    def test_parses_boolean_field(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("---\nauto_approve: true\
```

## Risultato

- Exit code: 0
- Durata: 210s
- Successo: Si
