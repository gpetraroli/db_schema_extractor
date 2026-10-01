# db_schema_extractor

Extract tables, columns, primary keys, and foreign keys from PostgreSQL or Oracle into one JSON file.

Requires Python 3.13 or newer.

## Install

```bash
uv sync
```

## Usage

```bash
uv run db_schema_extractor URI OUTPUT_FOLDER [--schema NAME ...] [--file_name NAME]
```

`URI` selects the database. `OUTPUT_FOLDER` is created if it does not exist. The default file name is `{database}_{db-type}-{YYYY-MM-DD-HH-MM-SS}.json`. `--file_name` sets the file name only; any directory in that argument is ignored. An existing file with the same name is overwritten.

With no `--schema`, the tool reads the session schema (`current_schema()` on PostgreSQL, `CURRENT_SCHEMA` on Oracle). Repeat `--schema` to extract more than one. Names are folded to lowercase on PostgreSQL and uppercase on Oracle.

```bash
uv run db_schema_extractor "postgresql://user:password@localhost:5432/app" ./out
uv run db_schema_extractor "postgresql://user:password@localhost:5432/app" ./out --schema public --schema sales

uv run db_schema_extractor "oracle://user:password@dbhost:1521/FREEPDB1" ./out
uv run db_schema_extractor "oracle://user:password@dbhost:1521/?sid=ORCL" ./out --schema hr
```

PostgreSQL accepts `postgresql://` and `postgres://`. Oracle uses `oracle://user:password@host[:port]/service_name`. The port defaults to `1521`. A SID can be passed as `?sid=ORCL` when the path has no service name. Percent-encode characters that are special in a URI, including `@` in the password (`%40`).

The connection URI is a process argument, so the password is visible to other users on the machine and is stored in shell history.

## What is extracted

Each dump contains base tables in the selected schemas:

- PostgreSQL: ordinary and partitioned tables.
- Oracle: tables visible in `ALL_TABLES`, excluding nested tables and index-organized overflow tables.

Views, indexes, unique constraints, and check constraints are not included.

Every foreign key is stored on its table, including composite keys and more than one foreign key on the same column. `columns` and `target_columns` stay in the same order, so each entry is one edge. A dump of a single schema uses bare table names. A dump of several schemas names tables `schema.table`, and foreign keys use that same form. A foreign key that points at another schema uses `schema.table` even in a single-schema dump. The referenced table is included in this file only when its schema was selected. A dump of another database stays a separate file; a later graph can link them when a target name matches a table there.

PostgreSQL column types come from `format_type`, so length and precision are kept (`character varying(40)`, `numeric(10,2)`). Oracle column types are the data-dictionary type name, without length or precision (`VARCHAR2`, `NUMBER`). Descriptions are table and column comments.

## Output

```json
{
  "database_name": "app",
  "tables": [
    {
      "name": "orders",
      "description": "Customer orders",
      "columns": [
        {
          "name": "id",
          "data_type": "integer",
          "is_nullable": false,
          "is_primary_key": true,
          "description": null
        },
        {
          "name": "customer_id",
          "data_type": "integer",
          "is_nullable": false,
          "is_primary_key": false,
          "description": null
        }
      ],
      "foreign_keys": [
        {
          "name": "orders_customer_id_fkey",
          "columns": ["customer_id"],
          "target_table": "customers",
          "target_columns": ["id"]
        }
      ]
    }
  ]
}
```
