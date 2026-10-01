import oracledb
from urllib.parse import parse_qs, unquote, urlparse

from .base_extractor import BaseExtractor
from .models import ColumnMetadata, SchemaDump, TableMetadata

class OracleExtractor(BaseExtractor):
    db_type = "oracle"

    def connect(self):
        self.connection = oracledb.connect(**oracle_connect_params(self.connection_uri))

    def disconnect(self):
        if self.connection:
            self.connection.close()

    def extract_schema(self) -> SchemaDump:
        with self.connection.cursor() as cursor:
            database_name = _fetch_dicts(
                cursor,
                "SELECT SYS_CONTEXT('USERENV', 'DB_NAME') AS database_name FROM dual",
            )[0]["database_name"]
            visible_tables = _visible_tables(cursor)
            if not visible_tables:
                return SchemaDump(database_name=database_name, tables=[])

            table_rows = _rows_by_owner(cursor, visible_tables, """
                SELECT
                    t.owner,
                    t.table_name,
                    c.comments AS table_description
                FROM all_tables t
                LEFT JOIN all_tab_comments c
                    ON c.owner = t.owner
                   AND c.table_name = t.table_name
                   AND c.table_type = 'TABLE'
                WHERE t.owner = :owner
                  AND t.table_name IN ({tables})
                ORDER BY t.table_name
            """)
            column_rows = _rows_by_owner(cursor, visible_tables, """
                SELECT
                    col.owner,
                    col.table_name,
                    col.column_name,
                    col.data_type,
                    col.nullable,
                    cc.comments AS description
                FROM all_tab_columns col
                LEFT JOIN all_col_comments cc
                    ON cc.owner = col.owner
                   AND cc.table_name = col.table_name
                   AND cc.column_name = col.column_name
                WHERE col.owner = :owner
                  AND col.table_name IN ({tables})
                ORDER BY col.table_name, col.column_id
            """)
            primary_key_rows = _rows_by_owner(cursor, visible_tables, """
                SELECT cons.owner, cols.table_name, cols.column_name
                FROM all_constraints cons
                JOIN all_cons_columns cols
                    ON cons.owner = cols.owner
                   AND cons.constraint_name = cols.constraint_name
                WHERE cons.constraint_type = 'P'
                  AND cons.owner = :owner
                  AND cons.table_name IN ({tables})
            """)
            foreign_key_rows = _rows_by_owner(cursor, visible_tables, """
                SELECT
                    cons.owner,
                    cols.table_name,
                    cols.column_name,
                    rcols.owner AS foreign_owner,
                    rcols.table_name AS foreign_table_name,
                    rcols.column_name AS foreign_column_name
                FROM all_constraints cons
                JOIN all_cons_columns cols
                    ON cons.owner = cols.owner
                   AND cons.constraint_name = cols.constraint_name
                JOIN all_constraints rcons
                    ON cons.r_owner = rcons.owner
                   AND cons.r_constraint_name = rcons.constraint_name
                JOIN all_cons_columns rcols
                    ON rcons.owner = rcols.owner
                   AND rcons.constraint_name = rcols.constraint_name
                   AND cols.position = rcols.position
                WHERE cons.constraint_type = 'R'
                  AND cons.owner = :owner
                  AND cons.table_name IN ({tables})
            """)

        return _schema_from_rows(
            database_name,
            table_rows,
            column_rows,
            primary_key_rows,
            foreign_key_rows,
        )


def oracle_connect_params(uri: str) -> dict:
    parsed = urlparse(uri)
    if parsed.scheme != "oracle":
        raise ValueError(f"Unsupported Oracle URI scheme: {parsed.scheme or 'missing'}")
    if not parsed.username or parsed.password is None or not parsed.hostname:
        raise ValueError("Oracle URI must include user, password, and host")

    query = parse_qs(parsed.query)
    port = parsed.port or 1521
    service_name = parsed.path.lstrip("/") or _first(query, "service_name")
    sid = _first(query, "sid")
    if service_name:
        dsn = f"{parsed.hostname}:{port}/{service_name}"
    elif sid:
        dsn = oracledb.makedsn(parsed.hostname, port, sid=sid)
    else:
        raise ValueError("Oracle URI must include a service name or sid")

    return {
        "user": unquote(parsed.username),
        "password": unquote(parsed.password),
        "dsn": dsn,
    }


def _schema_from_rows(
    database_name: str,
    table_rows: list[dict],
    column_rows: list[dict],
    primary_key_rows: list[dict],
    foreign_key_rows: list[dict],
) -> SchemaDump:
    qualify_names = len({row["owner"] for row in table_rows}) > 1
    primary_keys = {
        (row["owner"], row["table_name"], row["column_name"]) for row in primary_key_rows
    }
    foreign_keys: dict[tuple[str, str, str], str] = {}
    for row in foreign_key_rows:
        key = (row["owner"], row["table_name"], row["column_name"])
        if key in foreign_keys:
            continue
        target = f"{row['foreign_table_name']}.{row['foreign_column_name']}"
        if row["foreign_owner"] != row["owner"]:
            target = f"{row['foreign_owner']}.{target}"
        foreign_keys[key] = target

    tables = {
        (row["owner"], row["table_name"]): TableMetadata(
            name=_table_name(row["owner"], row["table_name"], qualify_names),
            description=row["table_description"],
            columns=[],
        )
        for row in table_rows
    }
    for row in column_rows:
        table = tables.get((row["owner"], row["table_name"]))
        if table is None:
            continue
        key = (row["owner"], row["table_name"], row["column_name"])
        table.columns.append(ColumnMetadata(
            name=row["column_name"],
            data_type=row["data_type"],
            is_nullable=row["nullable"] == "Y",
            is_primary_key=key in primary_keys,
            foreign_key_target=foreign_keys.get(key),
            description=row["description"],
        ))

    return SchemaDump(database_name=database_name, tables=list(tables.values()))


def _visible_tables(cursor) -> list[tuple[str, str]]:
    owned = _fetch_dicts(cursor, """
        SELECT owner, table_name
        FROM all_tables
        WHERE owner = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA')
          AND nested = 'NO'
          AND iot_name IS NULL
    """)
    referenced = _fetch_dicts(cursor, """
        SELECT DISTINCT referenced_owner AS owner, referenced_name AS table_name
        FROM all_dependencies
        WHERE owner = USER
          AND referenced_type = 'TABLE'
    """)
    synonyms = _fetch_dicts(cursor, """
        SELECT DISTINCT table_owner AS owner, table_name
        FROM all_synonyms
        WHERE owner = USER
          AND table_owner IS NOT NULL
    """)
    candidates: dict[str, set[str]] = {}
    for row in (*owned, *referenced, *synonyms):
        if row["owner"] and row["table_name"]:
            candidates.setdefault(row["owner"], set()).add(row["table_name"])

    visible = []
    for owner, names in candidates.items():
        rows = _rows_by_owner(cursor, [(owner, name) for name in names], """
            SELECT owner, table_name
            FROM all_tables
            WHERE owner = :owner
              AND table_name IN ({tables})
              AND nested = 'NO'
              AND iot_name IS NULL
            ORDER BY table_name
        """)
        visible.extend((row["owner"], row["table_name"]) for row in rows)
    return visible


def _rows_by_owner(cursor, tables: list[tuple[str, str]], query: str) -> list[dict]:
    by_owner: dict[str, list[str]] = {}
    for owner, table_name in tables:
        by_owner.setdefault(owner, []).append(table_name)

    rows = []
    for owner, names in by_owner.items():
        for offset in range(0, len(names), 500):
            placeholders, binds = _in_binds(names[offset:offset + 500])
            binds["owner"] = owner
            rows.extend(_fetch_dicts(cursor, query.format(tables=placeholders), binds))
    return rows


def _in_binds(names: list[str]) -> tuple[str, dict[str, str]]:
    binds = {f"table_{index}": name for index, name in enumerate(names)}
    placeholders = ", ".join(f":table_{index}" for index in range(len(names)))
    return placeholders, binds


def _table_name(owner: str, table_name: str, qualify: bool) -> str:
    if qualify:
        return f"{owner}.{table_name}"
    return table_name


def _fetch_dicts(cursor, query: str, parameters: dict | None = None) -> list[dict]:
    cursor.execute(query, parameters or {})
    names = [column[0].lower() for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None
