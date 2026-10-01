import psycopg
from psycopg.rows import dict_row

from .base_extractor import BaseExtractor
from .models import ColumnMetadata, SchemaDump, TableMetadata

_TABLES_QUERY = """
    SELECT
        n.nspname AS table_schema,
        c.relname AS table_name,
        pg_catalog.obj_description(c.oid, 'pg_class') AS description
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %(schema)s
      AND c.relkind IN ('r', 'p')
    ORDER BY c.relname
"""

_COLUMNS_QUERY = """
    SELECT
        n.nspname AS table_schema,
        c.relname AS table_name,
        a.attname AS column_name,
        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
        NOT a.attnotnull AS is_nullable,
        pg_catalog.col_description(c.oid, a.attnum) AS description
    FROM pg_catalog.pg_attribute a
    JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %(schema)s
      AND c.relkind IN ('r', 'p')
      AND a.attnum > 0
      AND NOT a.attisdropped
    ORDER BY c.relname, a.attnum
"""

_PRIMARY_KEYS_QUERY = """
    SELECT
        n.nspname AS table_schema,
        c.relname AS table_name,
        a.attname AS column_name
    FROM pg_catalog.pg_constraint con
    JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN LATERAL unnest(con.conkey) AS key(attnum) ON true
    JOIN pg_catalog.pg_attribute a
        ON a.attrelid = c.oid
       AND a.attnum = key.attnum
    WHERE con.contype = 'p'
      AND n.nspname = %(schema)s
"""

_FOREIGN_KEYS_QUERY = """
    SELECT
        n.nspname AS table_schema,
        c.relname AS table_name,
        a.attname AS column_name,
        fn.nspname AS foreign_schema,
        fc.relname AS foreign_table_name,
        fa.attname AS foreign_column_name
    FROM pg_catalog.pg_constraint con
    JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_class fc ON fc.oid = con.confrelid
    JOIN pg_catalog.pg_namespace fn ON fn.oid = fc.relnamespace
    JOIN LATERAL unnest(con.conkey, con.confkey)
        WITH ORDINALITY AS cols(attnum, fattnum, ord) ON true
    JOIN pg_catalog.pg_attribute a
        ON a.attrelid = c.oid
       AND a.attnum = cols.attnum
    JOIN pg_catalog.pg_attribute fa
        ON fa.attrelid = fc.oid
       AND fa.attnum = cols.fattnum
    WHERE con.contype = 'f'
      AND n.nspname = %(schema)s
    ORDER BY c.relname, con.conname, cols.ord
"""


class PostgresExtractor(BaseExtractor):
    db_type = "postgres"

    def connect(self):
        self.connection = psycopg.connect(self.connection_uri, row_factory=dict_row)

    def disconnect(self):
        if self.connection:
            self.connection.close()

    def extract_schema(self) -> SchemaDump:
        schema = "public"
        with self.connection.cursor() as cursor:
            table_rows = cursor.execute(_TABLES_QUERY, {"schema": schema}).fetchall()
            column_rows = cursor.execute(_COLUMNS_QUERY, {"schema": schema}).fetchall()
            primary_key_rows = cursor.execute(_PRIMARY_KEYS_QUERY, {"schema": schema}).fetchall()
            foreign_key_rows = cursor.execute(_FOREIGN_KEYS_QUERY, {"schema": schema}).fetchall()

        return _schema_from_rows(
            self.connection.info.dbname,
            table_rows,
            column_rows,
            primary_key_rows,
            foreign_key_rows,
        )


def _schema_from_rows(
    database_name: str,
    table_rows: list[dict],
    column_rows: list[dict],
    primary_key_rows: list[dict],
    foreign_key_rows: list[dict],
) -> SchemaDump:
    primary_keys = {
        (row["table_schema"], row["table_name"], row["column_name"])
        for row in primary_key_rows
    }
    foreign_keys: dict[tuple[str, str, str], str] = {}
    for row in foreign_key_rows:
        key = (row["table_schema"], row["table_name"], row["column_name"])
        if key in foreign_keys:
            continue
        target = f"{row['foreign_table_name']}.{row['foreign_column_name']}"
        if row["foreign_schema"] != row["table_schema"]:
            target = f"{row['foreign_schema']}.{target}"
        foreign_keys[key] = target

    tables = {
        (row["table_schema"], row["table_name"]): TableMetadata(
            name=row["table_name"],
            description=row["description"],
            columns=[],
        )
        for row in table_rows
    }
    for row in column_rows:
        table = tables.get((row["table_schema"], row["table_name"]))
        if table is None:
            continue
        key = (row["table_schema"], row["table_name"], row["column_name"])
        table.columns.append(ColumnMetadata(
            name=row["column_name"],
            data_type=row["data_type"],
            is_nullable=row["is_nullable"],
            is_primary_key=key in primary_keys,
            foreign_key_target=foreign_keys.get(key),
            description=row["description"],
        ))

    return SchemaDump(database_name=database_name, tables=list(tables.values()))
