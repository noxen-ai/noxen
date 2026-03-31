"""Test per core/auto_discovery.py — scansione ecosistema microservizi."""

import pytest
from pathlib import Path

from core.auto_discovery import (
    AutoDiscovery,
    EcosystemMap,
    ServiceInfo,
    SERVICE_MARKERS,
    FRAMEWORK_PATTERNS,
)


class TestAutoDiscoveryScan:
    """Test scan() su strutture di progetto reali."""

    def test_scan_detects_services(self, tmp_project_dir: Path):
        """scan() trova i servizi nella directory."""
        discovery = AutoDiscovery(tmp_project_dir)
        eco = discovery.scan()

        assert isinstance(eco, EcosystemMap)
        assert eco.total_services >= 1
        assert eco.root_path == str(tmp_project_dir)

    def test_scan_detects_javascript(self, tmp_project_dir: Path):
        """Rileva JavaScript da package.json."""
        discovery = AutoDiscovery(tmp_project_dir)
        eco = discovery.scan()

        assert "javascript" in eco.languages

    def test_scan_detects_python_subservice(self, tmp_project_dir: Path):
        """Rileva Python sub-service da requirements.txt in backend/."""
        discovery = AutoDiscovery(tmp_project_dir)
        eco = discovery.scan()

        assert "python" in eco.languages

    def test_scan_detects_express_framework(self, tmp_project_dir: Path):
        """Rileva Express come framework da package.json."""
        discovery = AutoDiscovery(tmp_project_dir)
        eco = discovery.scan()

        assert "express" in eco.frameworks

    def test_scan_detects_db_config(self, tmp_project_dir: Path):
        """Rileva configurazione DB da .env."""
        discovery = AutoDiscovery(tmp_project_dir)
        eco = discovery.scan()

        has_db = any(s.has_db for s in eco.services)
        assert has_db, "Almeno un servizio dovrebbe avere DB config"

    def test_scan_detects_db_credentials(self, tmp_project_dir: Path):
        """Le credenziali DB vengono estratte correttamente."""
        discovery = AutoDiscovery(tmp_project_dir)
        eco = discovery.scan()

        db_services = [s for s in eco.services if s.has_db]
        assert len(db_services) > 0
        cfg = db_services[0].db_config
        assert cfg.get("host") == "localhost"
        assert cfg.get("database") == "testdb"

    def test_scan_php_laravel(self, php_laravel_dir: Path):
        """scan() rileva progetto PHP/Laravel con DB."""
        discovery = AutoDiscovery(php_laravel_dir)
        eco = discovery.scan()

        assert "php" in eco.languages
        assert "laravel" in eco.frameworks
        assert eco.db_configs_found >= 1

    def test_scan_laravel_db_credentials(self, php_laravel_dir: Path):
        """Credenziali DB Laravel estratte da .env con pattern DB_USERNAME."""
        discovery = AutoDiscovery(php_laravel_dir)
        eco = discovery.scan()

        db_svcs = [s for s in eco.services if s.has_db]
        assert len(db_svcs) > 0
        cfg = db_svcs[0].db_config
        assert cfg.get("user") == "forge"
        assert cfg.get("database") == "laravel"


class TestAutoDiscoveryEdgeCases:
    """Edge case e condizioni limite."""

    def test_scan_empty_directory(self, empty_project_dir: Path):
        """scan() su directory vuota ritorna mappa vuota senza errori."""
        discovery = AutoDiscovery(empty_project_dir)
        eco = discovery.scan()

        assert isinstance(eco, EcosystemMap)
        assert eco.total_services == 0
        assert eco.languages == []
        assert eco.frameworks == []

    def test_scan_nonexistent_directory(self, tmp_path: Path):
        """scan() su directory inesistente non crasha."""
        bad_path = tmp_path / "does-not-exist"
        discovery = AutoDiscovery(bad_path)
        eco = discovery.scan()

        # Non deve crashare, ma la mappa sara' vuota
        assert isinstance(eco, EcosystemMap)
        assert eco.total_services == 0

    def test_scan_skips_hidden_dirs(self, tmp_path: Path):
        """Le directory nascoste (.) vengono ignorate."""
        root = tmp_path / "proj"
        root.mkdir()
        hidden = root / ".hidden-service"
        hidden.mkdir()
        (hidden / "package.json").write_text('{"name": "hidden"}')

        discovery = AutoDiscovery(root)
        eco = discovery.scan()

        # .hidden-service NON deve comparire
        service_names = [s.name for s in eco.services]
        assert ".hidden-service" not in service_names

    def test_scan_skips_node_modules(self, tmp_path: Path):
        """node_modules/ viene ignorata anche se contiene marker file."""
        root = tmp_path / "proj"
        root.mkdir()
        (root / "package.json").write_text('{"name": "main"}')
        nm = root / "node_modules" / "express"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"name": "express"}')

        discovery = AutoDiscovery(root)
        eco = discovery.scan()

        service_names = [s.name for s in eco.services]
        assert "express" not in service_names


class TestAutoDiscoverySaveMap:
    """Test salvataggio mappa JSON."""

    def test_save_map_creates_file(self, tmp_project_dir: Path, tmp_path: Path):
        """save_map() crea il file ecosystem-map.json."""
        discovery = AutoDiscovery(tmp_project_dir)
        discovery.scan()

        output_dir = tmp_path / "output"
        path = discovery.save_map(output_dir)

        assert path.exists()
        assert path.name == "ecosystem-map.json"
        assert path.stat().st_size > 0

    def test_save_map_without_scan_triggers_scan(self, tmp_project_dir: Path, tmp_path: Path):
        """save_map() senza scan() precedente esegue scan automaticamente."""
        discovery = AutoDiscovery(tmp_project_dir)
        # Non chiamiamo scan() — save_map deve farlo
        output_dir = tmp_path / "output"
        path = discovery.save_map(output_dir)

        assert path.exists()


class TestServiceMarkers:
    """Test che le costanti di detection siano corrette."""

    def test_service_markers_cover_major_languages(self):
        """SERVICE_MARKERS copre i linguaggi principali."""
        languages = set(SERVICE_MARKERS.values())
        expected = {"php", "javascript", "python", "go", "ruby", "java", "rust"}
        assert expected.issubset(languages)

    def test_framework_patterns_cover_major_frameworks(self):
        """FRAMEWORK_PATTERNS copre i framework principali."""
        expected = {"laravel", "express", "django", "fastapi", "react", "angular", "vue"}
        assert expected.issubset(set(FRAMEWORK_PATTERNS.keys()))
