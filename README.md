# db_schema_extractor

Extract a database schema as SQL.

Requires Python 3.13 or newer.

## Supported databases

- PostgreSQL, via `pg_dump` on `PATH`
- Oracle, via `DBMS_METADATA` over the database connection

## Why of this project

A schema dump is useful, for example, to create a semantic relational graph with [Graphify](https://github.com/Graphify-Labs/graphify).

## Install

```bash
uv sync
```

The image below already contains Python and `pg_dump`. Use it when `pg_dump` is not installed on the machine. Oracle does not need a client tool.

```bash
docker build -t db-schema-extractor .
```

It includes PostgreSQL client 18, which can dump PostgreSQL 18 and older servers.

## Usage

```bash
uv run db_schema_extractor URI OUTPUT_FOLDER [--schema NAME ...] [--file_name NAME]
```

`URI` selects the database. `OUTPUT_FOLDER` is created if it does not exist. The default file name is `{database}_{db-type}-{YYYY-MM-DD-HH-MM-SS}.sql`. `--file_name` sets the file name only; any directory in that argument is ignored. An existing file with the same name is overwritten.

With no `--schema`, the tool reads the session schema (`current_schema()` on PostgreSQL, `CURRENT_SCHEMA` on Oracle). Repeat `--schema` to extract more than one. Names are folded to lowercase on PostgreSQL and uppercase on Oracle.

```bash
uv run db_schema_extractor "postgresql://user:password@localhost:5432/app" ./out
uv run db_schema_extractor "postgresql://user:password@localhost:5432/app" ./out --schema public --schema sales

uv run db_schema_extractor "oracle://user:password@dbhost:1521/FREEPDB1" ./out
uv run db_schema_extractor "oracle://user:password@dbhost:1521/?sid=ORCL" ./out --schema hr
```

PostgreSQL accepts `postgresql://` and `postgres://`. Oracle uses `oracle://user:password@host[:port]/service_name`. The port defaults to `1521`. A SID can be passed as `?sid=ORCL` when the path has no service name. Percent-encode characters that are special in a URI, including `@` in the password (`%40`).

The connection URI is a process argument, so the password is visible to other users on the machine and is stored in shell history.

With Docker, mount a host directory and pass that path as the output folder. A remote database is reached by its hostname, with no extra host mapping.

```bash
docker run --rm \
  -v "$PWD/out:/out" \
  db-schema-extractor \
  "postgresql://user:password@dbhost:5432/app" /out --schema public

docker run --rm \
  -v "$PWD/out:/out" \
  db-schema-extractor \
  "oracle://user:password@dbhost:1521/FREEPDB1" /out --schema hr
```

`localhost` inside the container is the container, so a database on the host is `host.docker.internal`. On Linux, add the host gateway.

```bash
docker run --rm --add-host=host.docker.internal:host-gateway \
  -v "$PWD/out:/out" \
  db-schema-extractor \
  "postgresql://user:password@host.docker.internal:5432/app" /out --schema public

docker run --rm --add-host=host.docker.internal:host-gateway \
  -v "$PWD/out:/out" \
  db-schema-extractor \
  "oracle://user:password@host.docker.internal:1521/FREEPDB1" /out --schema hr
```

## What is extracted

Each run writes one SQL file of schema DDL. Row data is not included.

PostgreSQL runs:

```bash
pg_dump --schema-only --no-owner --no-privileges \
  -d URI \
  -n schema \
  -f OUTPUT.sql
```

`PGCLIENTENCODING` is set to `UTF8`. One `-n` is passed for each selected schema. The file includes tables, views, indexes, sequences, routines, constraints, and comments. Ownership and privileges are omitted.

Oracle calls `DBMS_METADATA.GET_DDL` for sequences, tables, views, triggers, procedures, functions, packages, and package bodies in the selected schemas. Storage and tablespace clauses are omitted. An object that cannot be read is skipped and named on stderr.

## TODO

- Add connectors for other databases and APIs.
