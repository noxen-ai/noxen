"""Tests for the dashboard UI — Step 9.14."""

import pytest
from pathlib import Path


# ── Fixture: FastAPI TestClient ────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    from tests.conftest import override_tenant_auth

    override_tenant_auth(app)
    return TestClient(app)


# ── Test: Dashboard serves ─────────────────────────────────────────

class TestDashboardServes:
    def test_root_returns_200(self, client):
        """GET / returns 200 OK."""
        r = client.get("/")
        assert r.status_code == 200

    def test_root_is_html(self, client):
        """GET / returns HTML content."""
        r = client.get("/")
        assert "text/html" in r.headers.get("content-type", "")

    def test_dashboard_has_title(self, client):
        """Dashboard contains Noxen title."""
        r = client.get("/")
        assert "Noxen" in r.text


# ── Test: Static JS files served ───────────────────────────────────

class TestStaticJS:
    JS_FILES = [
        "/static/js/api.js",
        "/static/js/sse.js",
        "/static/js/app.js",
        "/static/js/components/overview.js",
        "/static/js/components/chat.js",
        "/static/js/components/research.js",
        "/static/js/components/skills.js",
        "/static/js/components/board.js",
        "/static/js/components/execution.js",
        "/static/js/components/notifications.js",
        "/static/js/components/settings.js",
        "/static/js/components/admin.js",
    ]

    @pytest.mark.parametrize("path", JS_FILES)
    def test_js_file_served(self, client, path):
        """Each JS file should be served as 200."""
        r = client.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"

    def test_api_js_has_neural_api(self, client):
        """api.js defines NoxenAPI object."""
        r = client.get("/static/js/api.js")
        assert "NoxenAPI" in r.text

    def test_sse_js_has_neural_sse(self, client):
        """sse.js defines NoxenSSE object."""
        r = client.get("/static/js/sse.js")
        assert "NoxenSSE" in r.text

    def test_app_js_has_noxen_app(self, client):
        """app.js defines noxenApp function."""
        r = client.get("/static/js/app.js")
        assert "noxenApp" in r.text


# ── Test: Dashboard has all tabs ───────────────────────────────────

class TestDashboardTabs:
    TABS = [
        "overview", "chat", "research", "skills",
        "board", "execution", "notifications", "settings", "admin",
    ]

    @pytest.mark.parametrize("tab", TABS)
    def test_tab_present_in_html(self, client, tab):
        """Each tab ID should appear in dashboard HTML."""
        r = client.get("/")
        assert tab in r.text

    def test_all_component_scripts_loaded(self, client):
        """Dashboard HTML includes all 9 component script tags."""
        r = client.get("/")
        for tab in self.TABS:
            assert f"components/{tab}.js" in r.text, f"Missing script for {tab}"


# ── Test: Dashboard loads AlpineJS ─────────────────────────────────

class TestAlpineJS:
    def test_alpine_cdn_loaded(self, client):
        """Dashboard loads AlpineJS from CDN."""
        r = client.get("/")
        assert "alpinejs" in r.text

    def test_x_data_on_body(self, client):
        """Body has x-data attribute for AlpineJS root component."""
        r = client.get("/")
        assert 'x-data="noxenApp()"' in r.text

    def test_x_show_for_tabs(self, client):
        """Dashboard uses x-show for tab switching."""
        r = client.get("/")
        assert "x-show=" in r.text


# ── Test: Dashboard loads Tailwind ─────────────────────────────────

class TestTailwind:
    def test_tailwind_cdn_loaded(self, client):
        """Dashboard loads Tailwind CSS from CDN."""
        r = client.get("/")
        assert "tailwindcss" in r.text

    def test_app_css_loaded(self, client):
        """Dashboard loads app.css stylesheet."""
        r = client.get("/")
        assert "app.css" in r.text


# ── Test: CSS file served ──────────────────────────────────────────

class TestStaticCSS:
    def test_app_css_served(self, client):
        """app.css is served correctly."""
        r = client.get("/static/css/app.css")
        assert r.status_code == 200

    def test_app_css_has_sidebar(self, client):
        """app.css contains sidebar styles."""
        r = client.get("/static/css/app.css")
        assert "sidebar-item" in r.text


# ── Test: Component JS file contents ──────────────────────────────

class TestComponentContents:
    """Verify each component JS defines its expected function."""

    COMPONENTS = {
        "overview": "overviewComponent",
        "chat": "chatComponent",
        "research": "researchComponent",
        "skills": "skillsComponent",
        "board": "boardComponent",
        "execution": "executionComponent",
        "notifications": "notificationsComponent",
        "settings": "settingsComponent",
        "admin": "adminComponent",
    }

    @pytest.mark.parametrize("name,func", list(COMPONENTS.items()))
    def test_component_defines_function(self, client, name, func):
        """Each component JS file defines its expected function."""
        r = client.get(f"/static/js/components/{name}.js")
        assert r.status_code == 200
        assert f"function {func}()" in r.text


# ── Test: JS file structure on disk ───────────────────────────────

class TestFileStructure:
    """Verify the new file structure exists on disk."""

    def test_components_dir_exists(self):
        components = Path(__file__).parent.parent / "ui" / "static" / "js" / "components"
        assert components.is_dir()

    def test_nine_component_files(self):
        components = Path(__file__).parent.parent / "ui" / "static" / "js" / "components"
        js_files = list(components.glob("*.js"))
        assert len(js_files) == 9, f"Expected 9 component files, got {len(js_files)}: {[f.name for f in js_files]}"

    def test_api_js_exists(self):
        f = Path(__file__).parent.parent / "ui" / "static" / "js" / "api.js"
        assert f.is_file()

    def test_sse_js_exists(self):
        f = Path(__file__).parent.parent / "ui" / "static" / "js" / "sse.js"
        assert f.is_file()

    def test_app_js_exists(self):
        f = Path(__file__).parent.parent / "ui" / "static" / "js" / "app.js"
        assert f.is_file()

    def test_app_css_exists(self):
        f = Path(__file__).parent.parent / "ui" / "static" / "css" / "app.css"
        assert f.is_file()
