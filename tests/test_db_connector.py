"""Test per core/db_connector.py — connettore MySQL read-only."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.db_connector import DBConnector, SchemaInfo, TableInfo


class TestDBConnectorInit:
    """Test creazione connettore."""

    def test_default_values(self):
        """Valori default corretti."""
        db = DBConnector()
        assert db.host == "localhost"
        assert db.port == 3306
        assert db.user == "root"
        assert db.password == ""
        assert db.database == ""
        assert db.is_connected is False

    def test_custom_values(self):
        """Valori custom vengono accettati."""
        db = DBConnector(
            host="db.example.com",
            port=3307,
            user="admin",
            password="secret",
            database="mydb",
        )
        assert db.host == "db.example.com"
        assert db.port == 3307
        assert db.user == "admin"
        assert db.database == "mydb"


class TestSchemaToText:
    """Test formattazione schema in testo per LLM context."""

    def test_empty_schema(self):
        """Schema vuoto produce output minimale."""
        schema = SchemaInfo(database="testdb")
        db = DBConnector(database="testdb")
        text = db.schema_to_text(schema)

        assert "testdb" in text
        assert "Tabelle: 0" in text

    def test_single_table(self):
        """Schema con una tabella formattata correttamente."""
        table = TableInfo(
            name="users",
            engine="InnoDB",
            row_count=1500,
            columns=[
                {"name": "id", "type": "int(11)", "nullable": "NO", "key": "PRI", "default": "", "extra": "auto_increment"},
                {"name": "email", "type": "varchar(255)", "nullable": "NO", "key": "", "default": "", "extra": ""},
                {"name": "name", "type": "varchar(100)", "nullable": "YES", "key": "", "default": "", "extra": ""},
            ],
            primary_key=["id"],
            foreign_keys=[],
            indexes=[],
        )
        schema = SchemaInfo(
            database="testdb",
            tables=[table],
            total_tables=1,
            total_rows=1500,
        )

        db = DBConnector(database="testdb")
        text = db.schema_to_text(schema)

        assert "TABLE users" in text
        assert "InnoDB" in text
        assert "1500" in text
        assert "id int(11) PK NOT NULL" in text
        assert "email varchar(255) NOT NULL" in text
        assert "name varchar(100) NULL" in text

    def test_foreign_key_in_output(self):
        """Le foreign key compaiono nell'output."""
        table = TableInfo(
            name="orders",
            columns=[
                {"name": "id", "type": "int", "nullable": "NO", "key": "PRI", "default": "", "extra": ""},
                {"name": "user_id", "type": "int", "nullable": "NO", "key": "MUL", "default": "", "extra": ""},
            ],
            primary_key=["id"],
            foreign_keys=[
                {"column": "user_id", "references_table": "users", "references_column": "id"},
            ],
        )
        schema = SchemaInfo(database="testdb", tables=[table], total_tables=1)

        db = DBConnector(database="testdb")
        text = db.schema_to_text(schema)

        assert "FK: user_id -> users.id" in text

    def test_multiple_tables(self):
        """Schema con piu' tabelle le elenca tutte."""
        tables = [
            TableInfo(name="users", columns=[], primary_key=[], foreign_keys=[]),
            TableInfo(name="orders", columns=[], primary_key=[], foreign_keys=[]),
            TableInfo(name="products", columns=[], primary_key=[], foreign_keys=[]),
        ]
        schema = SchemaInfo(database="shop", tables=tables, total_tables=3, total_rows=5000)

        db = DBConnector(database="shop")
        text = db.schema_to_text(schema)

        assert "TABLE users" in text
        assert "TABLE orders" in text
        assert "TABLE products" in text
        assert "Tabelle: 3" in text


class TestReadOnlyEnforcement:
    """Test che solo query SELECT siano permesse."""

    @pytest.mark.asyncio
    async def test_select_passes(self):
        """Query SELECT viene accettata (mock pool)."""
        db = DBConnector(database="testdb")

        # Mock del pool
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "name": "test"}])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        db._pool = mock_pool

        with patch.dict("sys.modules", {"aiomysql": MagicMock(DictCursor="dict")}):
            result = await db.query("SELECT * FROM users")

        # La query SELECT non deve essere bloccata
        assert result != [{"error": "Solo query SELECT/SHOW/DESCRIBE/EXPLAIN permesse (read-only)"}]

    @pytest.mark.asyncio
    async def test_insert_blocked(self):
        """Query INSERT viene bloccata."""
        db = DBConnector(database="testdb")
        result = await db.query("INSERT INTO users (name) VALUES ('hack')")

        assert len(result) == 1
        assert "error" in result[0]
        assert "read-only" in result[0]["error"].lower() or "SELECT" in result[0]["error"]

    @pytest.mark.asyncio
    async def test_update_blocked(self):
        """Query UPDATE viene bloccata."""
        db = DBConnector(database="testdb")
        result = await db.query("UPDATE users SET name='hack' WHERE id=1")

        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_delete_blocked(self):
        """Query DELETE viene bloccata."""
        db = DBConnector(database="testdb")
        result = await db.query("DELETE FROM users WHERE id=1")

        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_drop_blocked(self):
        """Query DROP viene bloccata."""
        db = DBConnector(database="testdb")
        result = await db.query("DROP TABLE users")

        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_show_passes(self):
        """Query SHOW viene accettata."""
        db = DBConnector(database="testdb")
        # Senza pool, fallira', ma non per il check read-only
        # Verifica che non venga bloccata dal filtro
        db._pool = None
        result = await db.query("SHOW TABLES")
        # Con pool=None, ritornera' errore di esecuzione, non di read-only
        if result and "error" in result[0]:
            assert "read-only" not in result[0]["error"].lower()

    @pytest.mark.asyncio
    async def test_describe_passes(self):
        """Query DESCRIBE viene accettata."""
        db = DBConnector(database="testdb")
        db._pool = None
        result = await db.query("DESCRIBE users")
        if result and "error" in result[0]:
            assert "read-only" not in result[0]["error"].lower()

    @pytest.mark.asyncio
    async def test_case_insensitive_blocking(self):
        """Il blocco funziona anche con case misto."""
        db = DBConnector(database="testdb")
        result = await db.query("insert INTO users VALUES (1)")
        assert "error" in result[0]

        result = await db.query("  DELETE from users")
        assert "error" in result[0]


class TestTableInfo:
    """Test dataclass TableInfo."""

    def test_default_values(self):
        """TableInfo ha default ragionevoli."""
        t = TableInfo(name="test")
        assert t.name == "test"
        assert t.columns == []
        assert t.primary_key == []
        assert t.foreign_keys == []
        assert t.indexes == []
        assert t.row_count == 0
        assert t.engine == ""
