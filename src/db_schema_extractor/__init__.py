import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .oracle_extractor import OracleExtractor
from .postgres_extractor import PostgresExtractor


def _schema_names(schemas: list[str] | None) -> list[str] | None:
    if not schemas:
        return None
    names = []
    for schema in schemas:
        name = schema.strip()
        if not name:
            raise ValueError("--schema must be a non-empty name")
        if name not in names:
            names.append(name)
    return names


def schema_file_name(database_name: str, db_type: str, when: datetime | None = None) -> str:
    timestamp = (when or datetime.now()).strftime("%Y-%m-%d-%H-%M-%S")
    safe_name = database_name.replace("/", "_").replace("\\", "_")
    return f"{safe_name}_{db_type}-{timestamp}.sql"


def extractor_for(uri: str, schemas: list[str] | None = None):
    scheme = urlparse(uri).scheme.lower()
    if scheme in {"postgres", "postgresql"}:
        return PostgresExtractor(uri, schemas)
    if scheme == "oracle":
        return OracleExtractor(uri, schemas)
    raise ValueError(f"Unsupported database URI scheme: {scheme or 'missing'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a database schema as SQL.")
    parser.add_argument("uri", help="Database connection URI")
    parser.add_argument("output_folder", help="Folder where the schema SQL is written")
    parser.add_argument(
        "--schema",
        action="append",
        dest="schemas",
        help=(
            "Schema to extract. Repeat to include more than one. "
            "Defaults to the session schema. Names are folded to lowercase "
            "on Postgres and uppercase on Oracle."
        ),
    )
    parser.add_argument(
        "--file_name",
        help="Output file name. Defaults to {db-name}_{db-type}-{YYYY-MM-DD-HH-MM-SS}.sql",
    )
    args = parser.parse_args()

    try:
        extractor = extractor_for(args.uri, _schema_names(args.schemas))
    except ValueError as exc:
        parser.error(str(exc))

    output_dir = Path(args.output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    with extractor:
        file_name = Path(args.file_name).name if args.file_name else schema_file_name(
            extractor.database_name,
            extractor.db_type,
        )
        output_path = output_dir / file_name
        extractor.write_sql(output_path)

    print(f"Successfully extracted schema to {output_path}.")
