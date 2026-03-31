"""Noxen - MySQL DB Connector (Read-Only).

Connessione sicura in sola lettura a MySQL:
  - SET SESSION TRANSACTION READ ONLY su ogni connessione
  - Schema dump: tabelle, colonne, tipi, FK, indici
  - Query SELECT on-demand per analisi
  - Mai INSERT/UPDATE/DELETE/DROP

Supporta connessione a DB XAMPP locali o remoti.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("noxen.db")


@dataclass
class TableInfo:
    """Informazioni su una tabella."""
    name: str
    columns: list[dict[str, str]] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[dict[str, str]] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    engine: str = ""


@dataclass
class SchemaInfo:
    """Schema completo di un database."""
    database: str
    tables: list[TableInfo] = field(default_factory=list)
    total_tables: int = 0
    total_rows: int = 0


class DBConnector:
    """Connettore MySQL in sola lettura per analisi."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self._pool = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Connetti al database in modalita' read-only."""
        try:
            import aiomysql
        except ImportError:
            logger.error("aiomysql non installato. Esegui: pip install aiomysql")
            return False

        try:
            self._pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                autocommit=True,
                minsize=1,
                maxsize=3,
            )

            # Forza read-only su ogni connessione
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SET SESSION TRANSACTION READ ONLY")
                    await cur.execute("SELECT 1")
                    await cur.fetchone()

            self._connected = True
            logger.info(f"Connesso a MySQL {self.host}:{self.port}/{self.database} (READ ONLY)")
            return True

        except Exception as e:
            logger.error(f"Connessione MySQL fallita: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Chiudi la connessione."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._connected = False
            logger.info("Disconnesso da MySQL")

    async def get_databases(self) -> list[str]:
        """Lista tutti i database disponibili."""
        rows = await self._execute("SHOW DATABASES")
        return [r[0] for r in rows if r[0] not in ("information_schema", "performance_schema", "mysql", "sys")]

    async def get_schema(self, database: str = "") -> SchemaInfo:
        """Dump completo dello schema di un database."""
        db = database or self.database
        if not db:
            return SchemaInfo(database="")

        schema = SchemaInfo(database=db)

        # Lista tabelle
        tables = await self._execute(
            "SELECT TABLE_NAME, ENGINE, TABLE_ROWS "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME",
            (db,)
        )

        for table_name, engine, row_count in tables:
            info = TableInfo(
                name=table_name,
                engine=engine or "",
                row_count=row_count or 0,
            )

            # Colonne
            cols = await self._execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, EXTRA "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION",
                (db, table_name)
            )
            for col_name, col_type, nullable, key, default, extra in cols:
                info.columns.append({
                    "name": col_name,
                    "type": col_type,
                    "nullable": nullable,
                    "key": key,
                    "default": str(default) if default is not None else "",
                    "extra": extra or "",
                })
                if key == "PRI":
                    info.primary_key.append(col_name)

            # Foreign keys
            fks = await self._execute(
                "SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
                "FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "AND REFERENCED_TABLE_NAME IS NOT NULL",
                (db, table_name)
            )
            for col, ref_table, ref_col in fks:
                info.foreign_keys.append({
                    "column": col,
                    "references_table": ref_table,
                    "references_column": ref_col,
                })

            # Indici
            idxs = await self._execute(
                "SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE "
                "FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY INDEX_NAME, SEQ_IN_INDEX",
                (db, table_name)
            )
            idx_map: dict[str, dict] = {}
            for idx_name, col, non_unique in idxs:
                if idx_name not in idx_map:
                    idx_map[idx_name] = {
                        "name": idx_name,
                        "columns": [],
                        "unique": not non_unique,
                    }
                idx_map[idx_name]["columns"].append(col)
            info.indexes = list(idx_map.values())

            schema.tables.append(info)

        schema.total_tables = len(schema.tables)
        schema.total_rows = sum(t.row_count for t in schema.tables)

        logger.info(f"Schema {db}: {schema.total_tables} tabelle, ~{schema.total_rows} righe")
        return schema

    async def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Esegui una query SELECT read-only. Ritorna lista di dict."""
        # Sicurezza: blocca query non-SELECT
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT") and not stripped.startswith("SHOW") and not stripped.startswith("DESCRIBE") and not stripped.startswith("EXPLAIN"):
            return [{"error": "Solo query SELECT/SHOW/DESCRIBE/EXPLAIN permesse (read-only)"}]

        try:
            import aiomysql
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute("SET SESSION TRANSACTION READ ONLY")
                    await cur.execute(sql, params)
                    rows = await cur.fetchall()
                    return list(rows)
        except Exception as e:
            logger.error(f"Query fallita: {e}")
            return [{"error": str(e)}]

    def schema_to_text(self, schema: SchemaInfo) -> str:
        """Converte lo schema in testo per il contesto LLM."""
        lines = [f"DATABASE: {schema.database}",
                 f"Tabelle: {schema.total_tables}, Righe totali: ~{schema.total_rows}", ""]

        for table in schema.tables:
            lines.append(f"TABLE {table.name} ({table.engine}, ~{table.row_count} righe)")
            for col in table.columns:
                pk = " PK" if col["name"] in table.primary_key else ""
                nullable = " NULL" if col["nullable"] == "YES" else " NOT NULL"
                lines.append(f"  {col['name']} {col['type']}{pk}{nullable}")
            for fk in table.foreign_keys:
                lines.append(f"  FK: {fk['column']} -> {fk['references_table']}.{fk['references_column']}")
            lines.append("")

        return "\n".join(lines)

    async def _execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Esegui query interna e ritorna tuple."""
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SET SESSION TRANSACTION READ ONLY")
                    await cur.execute(sql, params)
                    return list(await cur.fetchall())
        except Exception as e:
            logger.error(f"Execute fallito: {e}")
            return []
