# db_schema_extractor

Extract a database schema as SQL.

Requires Python 3.13 or newer.

## Supported databases

- PostgreSQL, via `pg_dump` on `PATH`
- Oracle, via `expdp` and `impdp` on `PATH`

## Why of this project

A schema dump is useful, for example, to create a semantic relational graph with [Graphify](https://github.com/Graphify-Labs/graphify).

## Install

```bash
uv sync
```

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

The connection URI is a process argument, so the password is visible to other users on the machine and is stored in shell history. Oracle user names and passwords cannot contain a double quote.

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

Oracle runs a metadata-only export, then renders that dump as SQL:

```bash
expdp user/password@CONNECT \
  schemas=SCHEMA \
  content=metadata_only \
  directory=DATA_PUMP_DIR \
  dumpfile=schema_meta.dmp \
  logfile=schema_exp.log

impdp user/password@CONNECT \
  directory=DATA_PUMP_DIR \
  dumpfile=schema_meta.dmp \
  sqlfile=schema_meta.sql \
  logfile=schema_imp.log
```

Data Pump writes the dump, logs, and SQL file on the database server, in the `DATA_PUMP_DIR` directory object. The connected user needs `READ` and `WRITE` on that directory. The tool copies the SQL file into `OUTPUT_FOLDER` and then removes the server-side dump, logs, and SQL file. A Data Pump exit code of 5 means the job finished with errors; those messages are printed and the SQL file is still copied when the job produced one.

## TODO

- Add connectors for other databases and APIs.
