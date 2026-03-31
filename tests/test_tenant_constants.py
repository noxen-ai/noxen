"""Tests for tenant_id constant alignment — FIX 4."""

import glob
import os
import re

import pytest


class TestTenantConstants:
    """Verify tenant constants are defined and consistent."""

    def test_qdrant_global_tenant(self):
        from core.qdrant_client import NoxenQdrantClient
        assert NoxenQdrantClient.GLOBAL_TENANT == "global"

    def test_qdrant_default_tenant(self):
        from core.qdrant_client import NoxenQdrantClient
        assert NoxenQdrantClient.DEFAULT_TENANT == "default"

    def test_skill_repo_global_tenant(self):
        from core.skills.repository import SkillRepository
        assert SkillRepository.GLOBAL_TENANT == "global"

    def test_tenant_repo_default_id(self):
        from core.tenants.repository import TenantRepository
        assert TenantRepository.DEFAULT_TENANT_ID == "default"

    def test_lifecycle_global_constant(self):
        from core.skills.lifecycle import GLOBAL_SKILLS_TENANT
        assert GLOBAL_SKILLS_TENANT == "global"

    def test_constants_aligned(self):
        """All GLOBAL constants match."""
        from core.qdrant_client import NoxenQdrantClient
        from core.skills.repository import SkillRepository
        from core.skills.lifecycle import GLOBAL_SKILLS_TENANT
        assert NoxenQdrantClient.GLOBAL_TENANT == SkillRepository.GLOBAL_TENANT
        assert NoxenQdrantClient.GLOBAL_TENANT == GLOBAL_SKILLS_TENANT

    def test_default_constants_aligned(self):
        """All DEFAULT constants match."""
        from core.qdrant_client import NoxenQdrantClient
        from core.tenants.repository import TenantRepository
        assert NoxenQdrantClient.DEFAULT_TENANT == TenantRepository.DEFAULT_TENANT_ID


class TestNoHardcodedTenantIds:
    """Verify no hardcoded tenant_id strings in core/ files."""

    # Patterns that indicate a hardcoded tenant_id
    HARDCODED_PATTERNS = [
        r'"tenant_id":\s*"default"',
        r'"tenant_id":\s*"global"',
        r"tenant_id\s*=\s*['\"]default['\"]",
        r"tenant_id\s*=\s*['\"]global['\"]",
    ]

    # Files that are ALLOWED to have these strings (constant definitions)
    ALLOWED_FILES = {
        "core/qdrant_client.py",       # defines DEFAULT_TENANT and GLOBAL_TENANT
        "core/tenants/repository.py",   # defines DEFAULT_TENANT_ID
        "core/skills/repository.py",    # defines GLOBAL_TENANT
        "core/skills/lifecycle.py",     # defines GLOBAL_SKILLS_TENANT
    }

    def _get_core_files(self):
        """Get all .py files in core/ and api/routes/."""
        root = os.path.dirname(os.path.dirname(__file__))
        files = glob.glob(os.path.join(root, "core", "**", "*.py"), recursive=True)
        files += glob.glob(os.path.join(root, "api", "routes", "*.py"))
        return files

    def _relative_path(self, filepath):
        root = os.path.dirname(os.path.dirname(__file__))
        return os.path.relpath(filepath, root)

    def test_no_hardcoded_default_tenant(self):
        """No core file uses hardcoded 'default' as tenant_id."""
        violations = []
        for filepath in self._get_core_files():
            relpath = self._relative_path(filepath)
            if relpath in self.ALLOWED_FILES:
                continue
            with open(filepath) as f:
                content = f.read()
            for pattern in self.HARDCODED_PATTERNS:
                matches = re.findall(pattern, content)
                if matches:
                    violations.append(f"{relpath}: {matches}")
        assert violations == [], (
            f"Hardcoded tenant_id found in:\n" +
            "\n".join(f"  - {v}" for v in violations)
        )

    def test_knowledge_base_uses_constant(self):
        """KnowledgeBase uses DEFAULT_TENANT constant."""
        import inspect
        from core.knowledge_base import KnowledgeBase
        source = inspect.getsource(KnowledgeBase)
        assert "DEFAULT_TENANT" in source or "NoxenQdrantClient" in source

    def test_ingestor_uses_constant(self):
        """Ingestor uses DEFAULT_TENANT constant."""
        import inspect
        from core.ingestor import Ingestor
        source = inspect.getsource(Ingestor)
        assert "DEFAULT_TENANT" in source or "NoxenQdrantClient" in source

    def test_event_router_uses_constant(self):
        """EventRouter uses DEFAULT_TENANT constant."""
        import inspect
        from core.event_router import EventRouter
        source = inspect.getsource(EventRouter)
        assert "DEFAULT_TENANT" in source or "NoxenQdrantClient" in source

    def test_project_manager_uses_constant(self):
        """ProjectManager uses DEFAULT_TENANT constant."""
        import inspect
        from core.project_manager import ProjectManager
        source = inspect.getsource(ProjectManager)
        assert "DEFAULT_TENANT" in source or "NoxenQdrantClient" in source
