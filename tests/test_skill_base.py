"""Test per core/skill_base.py — interfaccia base skill."""

import pytest

from core.skill_base import (
    Skill,
    SkillMetadata,
    SkillResult,
    SkillCategory,
    SkillPriority,
)


class TestSkillMetadata:
    """Test creazione e validazione SkillMetadata."""

    def test_create_minimal(self):
        """Creazione con soli campi obbligatori."""
        meta = SkillMetadata(name="test-skill", description="A test skill")
        assert meta.name == "test-skill"
        assert meta.description == "A test skill"

    def test_default_values(self):
        """I default sono corretti."""
        meta = SkillMetadata(name="x", description="y")
        assert meta.version == "0.1.0"
        assert meta.author == "unknown"
        assert meta.category == SkillCategory.CUSTOM
        assert meta.tags == []
        assert meta.parameters == {}
        assert meta.auto_approve is False
        assert meta.priority == 3
        assert meta.depends_on == []

    def test_full_creation(self):
        """Creazione con tutti i campi."""
        meta = SkillMetadata(
            name="security-scanner",
            description="Scans for vulnerabilities",
            version="2.0.0",
            author="Noxen",
            category=SkillCategory.CODE_ANALYSIS,
            tags=["security", "audit"],
            parameters={"type": "object", "properties": {"target": {"type": "string"}}},
            auto_approve=True,
            priority=1,
            depends_on=["code-reader"],
        )
        assert meta.name == "security-scanner"
        assert meta.version == "2.0.0"
        assert meta.category == SkillCategory.CODE_ANALYSIS
        assert meta.auto_approve is True
        assert "security" in meta.tags
        assert meta.depends_on == ["code-reader"]


class TestSkillResult:
    """Test SkillResult dataclass."""

    def test_success_result(self):
        """Risultato di successo."""
        result = SkillResult(success=True, data={"findings": 3})
        assert result.success is True
        assert result.data == {"findings": 3}
        assert result.error is None
        assert result.metadata == {}

    def test_failure_result(self):
        """Risultato di fallimento."""
        result = SkillResult(success=False, error="Connection refused")
        assert result.success is False
        assert result.error == "Connection refused"
        assert result.data is None

    def test_result_with_metadata(self):
        """Risultato con metadata aggiuntivi."""
        result = SkillResult(
            success=True,
            data="ok",
            metadata={"duration_ms": 150, "provider": "ollama"},
        )
        assert result.metadata["duration_ms"] == 150


class TestSkillCategory:
    """Test enum SkillCategory."""

    def test_all_categories_exist(self):
        """Verifica che tutte le categorie previste esistano."""
        expected = [
            "code_analysis", "code_generation", "search",
            "devops", "data", "integration", "utility", "custom",
        ]
        actual = [c.value for c in SkillCategory]
        for exp in expected:
            assert exp in actual, f"Categoria mancante: {exp}"

    def test_category_is_string(self):
        """SkillCategory e' anche una stringa."""
        assert isinstance(SkillCategory.CODE_ANALYSIS, str)
        assert SkillCategory.CODE_ANALYSIS == "code_analysis"


class TestSkillPriority:
    """Test enum SkillPriority."""

    def test_orchestrator_is_highest(self):
        """ORCHESTRATOR ha priorita' 1 (la piu' alta)."""
        assert SkillPriority.ORCHESTRATOR == 1

    def test_background_is_lowest(self):
        """BACKGROUND ha priorita' 5 (la piu' bassa)."""
        assert SkillPriority.BACKGROUND == 5

    def test_priority_order(self):
        """Le priorita' sono ordinate correttamente."""
        assert SkillPriority.ORCHESTRATOR < SkillPriority.PRIMARY
        assert SkillPriority.PRIMARY < SkillPriority.SECONDARY
        assert SkillPriority.SECONDARY < SkillPriority.UTILITY
        assert SkillPriority.UTILITY < SkillPriority.BACKGROUND


class TestSkillToToolSchema:
    """Test to_tool_schema() per compatibilita' OpenAI function calling."""

    def test_schema_structure(self):
        """to_tool_schema() produce struttura OpenAI-compatible."""

        class DummySkill(Skill):
            metadata = SkillMetadata(
                name="dummy",
                description="A dummy skill for testing",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            )

            async def execute(self, **kwargs):
                return SkillResult(success=True)

        skill = DummySkill()
        schema = skill.to_tool_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "dummy"
        assert schema["function"]["description"] == "A dummy skill for testing"
        assert "properties" in schema["function"]["parameters"]
        assert "query" in schema["function"]["parameters"]["properties"]

    def test_schema_empty_params(self):
        """to_tool_schema() con parametri vuoti produce schema minimale."""

        class MinimalSkill(Skill):
            metadata = SkillMetadata(name="minimal", description="Minimal")

            async def execute(self, **kwargs):
                return SkillResult(success=True)

        skill = MinimalSkill()
        schema = skill.to_tool_schema()

        assert schema["function"]["parameters"]["type"] == "object"
        assert schema["function"]["parameters"]["properties"] == {}

    def test_schema_is_valid_json_serializable(self):
        """Lo schema deve essere serializzabile in JSON."""
        import json

        class JsonSkill(Skill):
            metadata = SkillMetadata(
                name="json-test",
                description="JSON serialization test",
                parameters={"type": "object", "properties": {}},
            )

            async def execute(self, **kwargs):
                return SkillResult(success=True)

        skill = JsonSkill()
        schema = skill.to_tool_schema()

        # Non deve sollevare eccezioni
        serialized = json.dumps(schema)
        assert isinstance(serialized, str)
        assert len(serialized) > 0


class TestSkillSubclassEnforcement:
    """Test che le subclass di Skill rispettino il contratto."""

    def test_missing_metadata_raises(self):
        """Subclass senza metadata solleva TypeError."""
        with pytest.raises(TypeError, match="must define a 'metadata'"):

            class BadSkill(Skill):
                async def execute(self, **kwargs):
                    return SkillResult(success=True)

    def test_repr(self):
        """__repr__ e' leggibile."""

        class ReprSkill(Skill):
            metadata = SkillMetadata(name="repr-test", description="x", version="1.2.3")

            async def execute(self, **kwargs):
                return SkillResult(success=True)

        skill = ReprSkill()
        assert "repr-test" in repr(skill)
        assert "1.2.3" in repr(skill)
