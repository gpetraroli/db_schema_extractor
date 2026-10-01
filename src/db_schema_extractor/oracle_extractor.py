import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import oracledb

from .base_extractor import BaseExtractor

_OBJECT_TYPES = (
    "SEQUENCE",
    "TABLE",
    "VIEW",
    "TRIGGER",
    "PROCEDURE",
    "FUNCTION",
    "PACKAGE",
    "PACKAGE BODY",
)

_SET_TRANSFORMS = """
BEGIN
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'PRETTY', true);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SQLTERMINATOR', true);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SEGMENT_ATTRIBUTES', false);
END;
"""


class OracleExtractor(BaseExtractor):
    db_type = "oracle"
    required_tools = ()

    def connect(self):
        self.connection = oracledb.connect(**oracle_connect_params(self.connection_uri))
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT SYS_CONTEXT('USERENV', 'DB_NAME') FROM dual")
            self._database_name = cursor.fetchone()[0]

    def disconnect(self):
        if self.connection:
            self.connection.close()

    def write_sql(self, output_path: Path) -> None:
        schemas = _selected_schemas(self.connection, self.schemas)
        partial = output_path.with_suffix(output_path.suffix + ".partial")
        try:
            with self.connection.cursor() as cursor, partial.open("w", encoding="utf-8") as handle:
                cursor.execute(_SET_TRANSFORMS)
                for schema in schemas:
                    for object_type, object_name in _objects(cursor, schema):
                        ddl = _ddl(cursor, object_type, object_name, schema)
                        if not ddl:
                            continue
                        handle.write(ddl.strip())
                        handle.write("\n\n")
            partial.replace(output_path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise


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


def _selected_schemas(connection, schemas: list[str] | None) -> list[str]:
    if not schemas:
        with connection.cursor() as cursor:
            cursor.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM dual")
            schema = cursor.fetchone()[0]
        if not schema:
            raise ValueError("No schema selected and the session has no current schema")
        schemas = [schema]

    selected = []
    for schema in schemas:
        name = schema.upper()
        if name not in selected:
            selected.append(name)
    return selected


def _objects(cursor, schema: str) -> list[tuple[str, str]]:
    placeholders = ", ".join(f":type_{index}" for index in range(len(_OBJECT_TYPES)))
    order = " ".join(
        f"WHEN '{object_type}' THEN {index}" for index, object_type in enumerate(_OBJECT_TYPES)
    )
    binds = {f"type_{index}": object_type for index, object_type in enumerate(_OBJECT_TYPES)}
    binds["schema"] = schema
    cursor.execute(f"""
        SELECT object_type, object_name
        FROM all_objects
        WHERE owner = :schema
          AND object_type IN ({placeholders})
          AND generated = 'N'
          AND object_name NOT LIKE 'BIN$%'
        ORDER BY CASE object_type {order} END, object_name
    """, binds)
    return cursor.fetchall()


def _ddl(cursor, object_type: str, object_name: str, schema: str) -> str:
    try:
        cursor.execute(
            "SELECT DBMS_METADATA.GET_DDL(:object_type, :object_name, :schema) FROM dual",
            object_type=object_type.replace(" ", "_"),
            object_name=object_name,
            schema=schema,
        )
        value = cursor.fetchone()[0]
    except oracledb.Error as exc:
        message = str(exc).splitlines()[0]
        print(f"Skipped {schema}.{object_name} ({object_type}): {message}", file=sys.stderr)
        return ""
    return _text(value)


def _text(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "read"):
        return value.read() or ""
    return str(value)


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None
