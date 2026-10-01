import psycopg
from psycopg.rows import dict_row

from .base_extractor import BaseExtractor
from .models import ColumnMetadata, ForeignKeyMetadata, SchemaDump, TableMetadata

_TABLES_QUERY = """
    SELECT
        n.nspname AS table_schema,
        c.relname AS table_name,
        pg_catalog.obj_description(c.oid, 'pg_class') AS description
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = ANY(%(schemas)s)
      AND c.relkind IN ('r', 'p')
    ORDER BY n.nspname, c.relname
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
    WHERE n.nspname = ANY(%(schemas)s)
      AND c.relkind IN ('r', 'p')
      AND a.attnum > 0
      AND NOT a.attisdropped
    ORDER BY n.nspname, c.relname, a.attnum
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
      AND n.nspname = ANY(%(schemas)s)
"""

_FOREIGN_KEYS_QUERY = """
    SELECT
        n.nspname AS table_schema,
        c.relname AS table_name,
        con.conname AS constraint_name,
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
      AND n.nspname = ANY(%(schemas)s)
    ORDER BY n.nspname, c.relname, con.conname, cols.ord
"""


class PostgresExtractor(BaseExtractor):
    db_type = "postgres"

    def connect(self):
        self.connection = psycopg.connect(self.connection_uri, row_factory=dict_row)

    def disconnect(self):
        if self.connection:
            self.connection.close()

    def extract_schema(self) -> SchemaDump:
        with self.connection.cursor() as cursor:
            schemas = _selected_schemas(cursor, self.schemas)
            params = {"schemas": schemas}
            table_rows = cursor.execute(_TABLES_QUERY, params).fetchall()
            column_rows = cursor.execute(_COLUMNS_QUERY, params).fetchall()
            primary_key_rows = cursor.execute(_PRIMARY_KEYS_QUERY, params).fetchall()
            foreign_key_rows = cursor.execute(_FOREIGN_KEYS_QUERY, params).fetchall()

        return _schema_from_rows(
            self.connection.info.dbname,
            table_rows,
            column_rows,
            primary_key_rows,
            foreign_key_rows,
        )


def _selected_schemas(cursor, schemas: list[str] | None) -> list[str]:
    if schemas:
        selected = []
        for schema in schemas:
            name = schema.lower()
            if name not in selected:
                selected.append(name)
        return selected

    schema = cursor.execute("SELECT current_schema() AS schema").fetchone()["schema"]
    if not schema:
        raise ValueError("No schema selected and the session has no current schema")
    return [schema]


def _schema_from_rows(
    database_name: str,
    table_rows: list[dict],
    column_rows: list[dict],
    primary_key_rows: list[dict],
    foreign_key_rows: list[dict],
) -> SchemaDump:
    qualify_names = len({row["table_schema"] for row in table_rows}) > 1
    primary_keys = {
        (row["table_schema"], row["table_name"], row["column_name"])
        for row in primary_key_rows
    }
    foreign_keys = _foreign_keys(foreign_key_rows, qualify_names)

    tables = {
        (row["table_schema"], row["table_name"]): TableMetadata(
            name=_table_name(row["table_schema"], row["table_name"], qualify_names),
            description=row["description"],
            columns=[],
            foreign_keys=foreign_keys.get((row["table_schema"], row["table_name"]), []),
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
            description=row["description"],
        ))

    return SchemaDump(database_name=database_name, tables=list(tables.values()))


def _foreign_keys(rows: list[dict], qualify_names: bool) -> dict[tuple[str, str], list[ForeignKeyMetadata]]:
    by_table: dict[tuple[str, str], list[ForeignKeyMetadata]] = {}
    by_constraint: dict[tuple[str, str, str], ForeignKeyMetadata] = {}
    for row in rows:
        table_key = (row["table_schema"], row["table_name"])
        constraint_key = (*table_key, row["constraint_name"])
        foreign_key = by_constraint.get(constraint_key)
        if foreign_key is None:
            target_table = row["foreign_table_name"]
            if qualify_names or row["foreign_schema"] != row["table_schema"]:
                target_table = f"{row['foreign_schema']}.{target_table}"
            foreign_key = ForeignKeyMetadata(
                name=row["constraint_name"],
                columns=[],
                target_table=target_table,
                target_columns=[],
            )
            by_constraint[constraint_key] = foreign_key
            by_table.setdefault(table_key, []).append(foreign_key)
        foreign_key.columns.append(row["column_name"])
        foreign_key.target_columns.append(row["foreign_column_name"])
    return by_table


def _table_name(schema: str, table_name: str, qualify: bool) -> str:
    if qualify:
        return f"{schema}.{table_name}"
    return table_name
