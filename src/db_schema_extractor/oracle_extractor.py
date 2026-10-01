import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import oracledb

from .base_extractor import BaseExtractor, run_tool

DUMP_DIRECTORY = "DATA_PUMP_DIR"
_DATA_PUMP_OK = (0, 5)

_READ_FILE = """
DECLARE
    l_bfile BFILE;
    l_clob CLOB;
    l_dest_offset INTEGER := 1;
    l_src_offset INTEGER := 1;
    l_lang_context INTEGER := DBMS_LOB.DEFAULT_LANG_CTX;
    l_warning INTEGER;
BEGIN
    l_bfile := BFILENAME(:directory, :filename);
    DBMS_LOB.OPEN(l_bfile, DBMS_LOB.LOB_READONLY);
    DBMS_LOB.CREATETEMPORARY(l_clob, TRUE);
    DBMS_LOB.LOADCLOBFROMFILE(
        l_clob,
        l_bfile,
        DBMS_LOB.LOBMAXSIZE,
        l_dest_offset,
        l_src_offset,
        0,
        l_lang_context,
        l_warning
    );
    DBMS_LOB.CLOSE(l_bfile);
    :content := l_clob;
END;
"""

_REMOVE_FILE = """
BEGIN
    UTL_FILE.FREMOVE(:directory, :filename);
END;
"""


class OracleExtractor(BaseExtractor):
    db_type = "oracle"

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
        directory_path = _directory_path(self.connection, DUMP_DIRECTORY)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        dumpfile = f"schema_meta_{stamp}.dmp"
        export_log = f"schema_exp_{stamp}.log"
        sqlfile = f"schema_meta_{stamp}.sql"
        import_log = f"schema_imp_{stamp}.log"
        connect = data_pump_connect(self.connection_uri)
        secrets = _secrets(self.connection_uri)
        try:
            code, output = run_tool(
                [
                    "expdp",
                    connect,
                    f"schemas={','.join(_expdp_schema(schema) for schema in schemas)}",
                    "content=metadata_only",
                    f"directory={DUMP_DIRECTORY}",
                    f"dumpfile={dumpfile}",
                    f"logfile={export_log}",
                    f"job_name=SCHEMA_EXP_{stamp}",
                    "reuse_dumpfiles=yes",
                ],
                ok_codes=_DATA_PUMP_OK,
                secrets=secrets,
            )
            _warn_if_errors("expdp", code, output, self.connection, export_log)

            code, output = run_tool(
                [
                    "impdp",
                    connect,
                    f"directory={DUMP_DIRECTORY}",
                    f"dumpfile={dumpfile}",
                    f"sqlfile={sqlfile}",
                    f"logfile={import_log}",
                    f"job_name=SCHEMA_IMP_{stamp}",
                ],
                ok_codes=_DATA_PUMP_OK,
                secrets=secrets,
            )
            _warn_if_errors("impdp", code, output, self.connection, import_log)
            _copy_directory_file(self.connection, DUMP_DIRECTORY, sqlfile, output_path)
        except Exception as exc:
            raise RuntimeError(
                f"{exc}\nCheck {DUMP_DIRECTORY} ({directory_path}) for "
                f"{dumpfile}, {export_log}, {sqlfile}, {import_log}"
            ) from exc

        for filename in (sqlfile, dumpfile, export_log, import_log):
            warning = _remove_server_file(self.connection, filename)
            if warning:
                print(warning, file=sys.stderr)


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


def data_pump_connect(uri: str) -> str:
    params = oracle_connect_params(uri)
    user = params["user"]
    password = params["password"]
    if '"' in user or '"' in password:
        raise ValueError("Oracle user and password cannot contain a double quote")
    return f'"{user}/{password}"@{params["dsn"]}'


def _secrets(uri: str) -> list[str]:
    params = oracle_connect_params(uri)
    return [params["password"], data_pump_connect(uri), uri]


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


def _expdp_schema(name: str) -> str:
    if re.fullmatch(r"[A-Z][A-Z0-9_$#]*", name):
        return name
    return '"' + name.replace('"', '""') + '"'


def _directory_path(connection, directory: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT directory_path
            FROM all_directories
            WHERE directory_name = :directory
            """,
            directory=directory,
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"Directory object {directory} is not visible to this user. "
            "Grant READ and WRITE on it before extracting."
        )
    return row[0]


def _copy_directory_file(connection, directory: str, filename: str, output_path: Path) -> None:
    partial = output_path.with_suffix(output_path.suffix + ".partial")
    try:
        with connection.cursor() as cursor:
            content = cursor.var(oracledb.DB_TYPE_CLOB)
            cursor.execute(_READ_FILE, directory=directory, filename=filename, content=content)
            value = content.getvalue()
            with partial.open("w", encoding="utf-8", newline="") as handle:
                _write_clob(value, handle)
        partial.replace(output_path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _write_clob(value, handle) -> None:
    if value is None:
        raise RuntimeError("The Data Pump SQL file was empty")
    if hasattr(value, "read"):
        wrote = False
        while True:
            chunk = value.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            wrote = True
        if not wrote:
            raise RuntimeError("The Data Pump SQL file was empty")
        return
    if not value:
        raise RuntimeError("The Data Pump SQL file was empty")
    handle.write(value)


def _read_text(connection, filename: str, limit: int = 20_000) -> str:
    try:
        with connection.cursor() as cursor:
            content = cursor.var(oracledb.DB_TYPE_CLOB)
            cursor.execute(
                _READ_FILE,
                directory=DUMP_DIRECTORY,
                filename=filename,
                content=content,
            )
            value = content.getvalue()
            if value is None:
                return ""
            text = value.read(limit + 1) if hasattr(value, "read") else str(value)
    except oracledb.Error:
        return ""
    if len(text) > limit:
        return text[:limit] + "\n..."
    return text


def _warn_if_errors(tool: str, code: int, output: str, connection, logfile: str) -> None:
    if code == 0:
        return
    detail = output.strip() or _read_text(connection, logfile).strip()
    message = f"{tool} completed with errors"
    if detail:
        message = f"{message}:\n{detail}"
    print(message, file=sys.stderr)


def _remove_server_file(connection, filename: str) -> str | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(_REMOVE_FILE, directory=DUMP_DIRECTORY, filename=filename)
    except oracledb.Error as exc:
        return f"Could not remove {DUMP_DIRECTORY}:{filename}: {exc}"
    return None


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None
