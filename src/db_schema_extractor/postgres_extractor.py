import os
from pathlib import Path

import psycopg

from .base_extractor import BaseExtractor, run_tool


class PostgresExtractor(BaseExtractor):
    db_type = "postgres"

    def connect(self):
        self.connection = psycopg.connect(self.connection_uri)
        self._database_name = self.connection.info.dbname

    def disconnect(self):
        if self.connection:
            self.connection.close()

    def write_sql(self, output_path: Path) -> None:
        command = [
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "-d",
            self.connection_uri,
        ]
        for schema in _selected_schemas(self.connection, self.schemas):
            command.extend(["-n", _schema_pattern(schema)])
        command.extend(["-f", str(output_path)])

        env = os.environ.copy()
        env["PGCLIENTENCODING"] = "UTF8"
        try:
            run_tool(command, secrets=[self.connection_uri], env=env)
        except Exception:
            output_path.unlink(missing_ok=True)
            raise


def _selected_schemas(connection, schemas: list[str] | None) -> list[str]:
    if schemas:
        selected = []
        for schema in schemas:
            name = schema.lower()
            if name not in selected:
                selected.append(name)
        return selected

    schema = connection.execute("SELECT current_schema()").fetchone()[0]
    if not schema:
        raise ValueError("No schema selected and the session has no current schema")
    return [schema]


def _schema_pattern(name: str) -> str:
    """pg_dump -n uses a psql pattern, so escape wildcard characters."""
    escaped = []
    for char in name:
        if char in "*?[\\":
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)
