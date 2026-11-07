"""Copies your existing SQLite data (meditrack.db) into a PostgreSQL database.

  # 1. Rehearsal. Reads and checks everything, writes NOTHING.
  python -m scripts.migrate_sqlite_to_postgres --source meditrack.db

  # 2. The real copy (only after the rehearsal says OK).
  python -m scripts.migrate_sqlite_to_postgres --source meditrack.db --execute

The PostgreSQL address is read from the TARGET_DATABASE_URL environment
variable, for example (PowerShell, this window only):

  $env:TARGET_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require"

Safety rules built into this script:
- The SQLite file is opened READ-ONLY. It is never changed, moved or deleted.
- With --execute a consistent backup copy of it is made first
  (<name>-backup-<date>.db, next to the original, never overwriting a file).
- Nothing is ever deleted or overwritten in PostgreSQL. If any table there
  already holds rows, the script stops and changes nothing.
- Everything is copied in ONE transaction and checked row by row against the
  source before it is committed. Any problem undoes the whole copy.
- User accounts, password hashes (copied exactly as stored, never re-hashed),
  roles, readings, conversations, audit log, ids and relationships are kept.
- Passwords and other secrets are never printed.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine

import app.models  # noqa: F401  (registers every table)
import app.models.admin_audit  # noqa: F401  (the administrator audit log table)
from app.database import Base
from app.database.session import normalize_database_url

CHUNK_SIZE = 500


class MigrationError(Exception):
    """A problem that stops the migration. Nothing has been written."""


@dataclass
class TableReport:
    name: str
    source_rows: int = 0
    copied_rows: int = 0
    cleaned_references: int = 0
    note: str = ""


@dataclass
class MigrationReport:
    tables: list[TableReport] = field(default_factory=list)
    committed: bool = False

    @property
    def total_rows(self) -> int:
        return sum(t.copied_rows for t in self.tables)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def open_sqlite_readonly(path: Path) -> Engine:
    """Open a SQLite file so that it cannot be modified."""
    path = Path(path).resolve()
    if not path.is_file():
        raise MigrationError(f"The SQLite file was not found: {path}")
    uri = f"{path.as_uri()}?mode=ro"
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))


def make_backup(path: Path) -> Path:
    """Copy the SQLite file safely (works even if it is in the middle of use)."""
    path = Path(path).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}-backup-{stamp}.db")
    counter = 2
    while backup.exists():  # never overwrite an earlier backup
        backup = path.with_name(f"{path.stem}-backup-{stamp}-{counter}.db")
        counter += 1
    source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(str(backup))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return backup


def _to_utc(value):
    """SQLite keeps times without a time zone (they are UTC)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return value


def _comparable(value):
    """Values compared after copying. Decimal('95.5') equals Decimal('95.50')."""
    return _to_utc(value)


def _describe(engine: Engine) -> str:
    """Host and database name only. Never the password."""
    url = engine.url
    if url.get_backend_name() == "sqlite":
        return f"SQLite file {url.database or '(memory)'}"
    return f"{url.get_backend_name()} database '{url.database}' on {url.host or '(local connection)'}"


# ---------------------------------------------------------------------------
# The migration
# ---------------------------------------------------------------------------


def _read_source(source: Engine, tables: list[Table], log):
    """Read every row of every table that exists in the source file.

    Returns {table name: (columns copied, list of row dicts)}.
    """
    inspector = inspect(source)
    existing = set(inspector.get_table_names())
    if "users" not in existing:
        raise MigrationError(
            "The SQLite file has no 'users' table. Is --source the right file?"
        )

    data: dict[str, tuple[list[str], list[dict]]] = {}
    with source.connect() as connection:
        for table in tables:
            if table.name not in existing:
                log(f"  note: '{table.name}' does not exist in the source file (treated as empty)")
                data[table.name] = ([], [])
                continue
            source_columns = {c["name"] for c in inspector.get_columns(table.name)}
            copy = [c for c in table.columns if c.name in source_columns]
            for column in table.columns:
                if column.name in source_columns:
                    continue
                if column.nullable or column.default is not None or column.server_default is not None:
                    log(
                        f"  note: '{table.name}.{column.name}' is missing in the source file; "
                        "its default value will be used"
                    )
                else:
                    raise MigrationError(
                        f"The source file lacks the required column '{table.name}.{column.name}'."
                    )
            primary_key = list(table.primary_key.columns)
            statement = select(*copy).order_by(*primary_key)
            rows = [dict(row) for row in connection.execute(statement).mappings()]
            data[table.name] = ([c.name for c in copy], rows)
    return data


def _check_references(tables: list[Table], data: dict, log) -> dict[str, int]:
    """Find rows that point at a record that is not there.

    A required reference to a missing record is a real problem (stop). An
    optional one (the audit log) is set to empty, which is exactly what the
    database itself does when a user is deleted.
    """
    known_ids: dict[str, set] = {}
    cleaned: dict[str, int] = {}
    problems: list[str] = []

    for table in tables:
        columns, rows = data[table.name]
        for foreign_key in table.foreign_keys:
            column = foreign_key.parent
            if column.name not in columns:
                continue
            referenced = foreign_key.column.table.name
            valid = known_ids.get(referenced, set())
            missing = 0
            for row in rows:
                value = row[column.name]
                if value is None or value in valid:
                    continue
                missing += 1
                if column.nullable:
                    row[column.name] = None
                    cleaned[table.name] = cleaned.get(table.name, 0) + 1
            if missing and not column.nullable:
                problems.append(
                    f"{missing} row(s) in '{table.name}' point at a '{referenced}' "
                    f"record that does not exist ('{column.name}')"
                )
            elif missing:
                log(
                    f"  note: {missing} reference(s) in '{table.name}.{column.name}' pointed at "
                    "deleted records and were set to empty"
                )
        primary_key = [c.name for c in table.primary_key.columns]
        if len(primary_key) == 1 and primary_key[0] in columns:
            known_ids[table.name] = {row[primary_key[0]] for row in rows}

    if problems:
        raise MigrationError(
            "The SQLite data has broken relationships, so nothing was copied:\n  - "
            + "\n  - ".join(problems)
        )
    return cleaned


def _reset_sequences(connection, tables: list[Table]) -> None:
    """After copying ids, make PostgreSQL's counters continue after the highest id."""
    for table in tables:
        primary_key = list(table.primary_key.columns)
        if len(primary_key) != 1:
            continue
        column = primary_key[0].name
        name = table.name  # fixed names from our own models, never user input
        connection.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{name}', '{column}'), "
                f"COALESCE((SELECT MAX({column}) FROM {name}), 1), "
                f"(SELECT COUNT(*) FROM {name}) > 0)"
            )
        )


def migrate(
    source: Engine,
    target: Engine,
    *,
    execute: bool = False,
    create_tables: bool = False,
    source_name: str | None = None,
    before_write=None,
    log=print,
) -> MigrationReport:
    """Copy all data from `source` to `target`.

    With execute=False the whole copy is performed and checked and then
    undone, so it is a safe rehearsal.

    `before_write` (optional) is called once, only when execute=True and only
    after every check has passed, right before the first row is written. The
    command line uses it to make the backup, so a refused run makes no backup.
    """
    warnings.filterwarnings("ignore", message=".*does \\*not\\* support Decimal.*")
    tables = list(Base.metadata.sorted_tables)  # parents before children

    log(f"Source: {source_name or _describe(source)} (opened read-only)")
    log(f"Target: {_describe(target)}")

    data = _read_source(source, tables, log)
    cleaned = _check_references(tables, data, log)

    report = MigrationReport()
    with target.connect() as connection:
        transaction = connection.begin()
        try:
            if create_tables:
                Base.metadata.create_all(bind=connection)  # only adds missing tables
            present = set(inspect(connection).get_table_names())
            missing_tables = [t.name for t in tables if t.name not in present]
            if missing_tables:
                raise MigrationError(
                    "These tables do not exist in the target database: "
                    + ", ".join(missing_tables)
                    + ".\nCreate them first with:  python -m scripts.create_tables  "
                    "(with DATABASE_URL pointing at the target), or add --create-tables."
                )

            filled = {}
            for table in tables:
                count = connection.execute(select(func.count()).select_from(table)).scalar_one()
                if count:
                    filled[table.name] = count
            if filled:
                raise MigrationError(
                    "The target database is not empty, so nothing was copied "
                    "(this script never merges or overwrites): "
                    + ", ".join(f"{name}={count} rows" for name, count in filled.items())
                )

            if execute and before_write is not None:
                before_write()

            for table in tables:
                columns, rows = data[table.name]
                item = TableReport(
                    name=table.name,
                    source_rows=len(rows),
                    cleaned_references=cleaned.get(table.name, 0),
                )
                prepared = [{k: _to_utc(v) for k, v in row.items()} for row in rows]
                for start in range(0, len(prepared), CHUNK_SIZE):
                    connection.execute(table.insert(), prepared[start : start + CHUNK_SIZE])

                # Check: read it back and compare with the source, row by row.
                if rows:
                    copy = [table.c[name] for name in columns]
                    order = list(table.primary_key.columns)
                    back = connection.execute(select(*copy).order_by(*order)).all()
                    if len(back) != len(prepared):
                        raise MigrationError(
                            f"Check failed for '{table.name}': {len(back)} rows copied, "
                            f"{len(prepared)} expected."
                        )
                    for original, copied in zip(prepared, back):
                        expected = tuple(_comparable(original[name]) for name in columns)
                        actual = tuple(_comparable(value) for value in copied)
                        if expected != actual:
                            raise MigrationError(
                                f"Check failed for '{table.name}': a copied row differs "
                                "from the source. Nothing was saved."
                            )
                item.copied_rows = len(rows)
                report.tables.append(item)

            if connection.dialect.name == "postgresql":
                _reset_sequences(connection, tables)

            if execute:
                transaction.commit()
                report.committed = True
            else:
                transaction.rollback()
        except BaseException:
            transaction.rollback()
            raise
    return report


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _print_report(report: MigrationReport, execute: bool) -> None:
    print()
    print(f"{'table':26s}{'in SQLite':>10s}{'copied':>10s}")
    print("-" * 46)
    for item in report.tables:
        print(f"{item.name:26s}{item.source_rows:>10d}{item.copied_rows:>10d}")
    print("-" * 46)
    print(f"{'total':26s}{sum(t.source_rows for t in report.tables):>10d}{report.total_rows:>10d}")
    print()
    if execute:
        print("DONE. All rows were copied, checked against the source, and saved.")
        print("Your SQLite file was not changed.")
    else:
        print("REHEARSAL OK. Every row was copied and checked, then undone.")
        print("Nothing was written to PostgreSQL. Run again with --execute to do it for real.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy MediTrack AI data from a SQLite file to PostgreSQL."
    )
    parser.add_argument("--source", default="meditrack.db", help="Path to the SQLite file")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Really save the copy. Without it the run is only a rehearsal.",
    )
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Create any missing tables in PostgreSQL first (never deletes anything).",
    )
    args = parser.parse_args(argv)

    raw_target = os.environ.get("TARGET_DATABASE_URL", "").strip()
    if not raw_target:
        print(
            "TARGET_DATABASE_URL is not set.\n"
            "PowerShell example (this window only):\n"
            '  $env:TARGET_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require"'
        )
        return 1
    target_url = normalize_database_url(raw_target)
    if not target_url.startswith("postgresql"):
        print("TARGET_DATABASE_URL must be a PostgreSQL address (postgresql://...).")
        return 1

    source_path = Path(args.source)
    target = None
    try:
        source = open_sqlite_readonly(source_path)
        target = create_engine(target_url, pool_pre_ping=True, connect_args={"prepare_threshold": None})

        if args.execute:
            print("EXECUTE: a backup of the SQLite file is made right before the copy starts.")
        else:
            print("REHEARSAL (no --execute): nothing will be written, no backup is made.")

        def backup_first() -> None:
            print(f"Backup of the SQLite file saved as: {make_backup(source_path)}")

        report = migrate(
            source,
            target,
            execute=args.execute,
            create_tables=args.create_tables,
            source_name=f"SQLite file {source_path.resolve()}",
            before_write=backup_first,
        )
    except MigrationError as error:
        print(f"\nSTOPPED: {error}")
        print("Nothing was changed in PostgreSQL.")
        return 1
    except Exception as error:  # connection problems, wrong password, and so on
        # The first line of the database's own message never contains the password.
        reason = str(getattr(error, "orig", error)).strip().splitlines() or [""]
        print(f"\nSTOPPED: {type(error).__name__}: {reason[0][:200]}")
        print("Nothing was changed in PostgreSQL.")
        print("Check the address, the network and that the password in the URL is correct.")
        return 1
    finally:
        if target is not None:
            target.dispose()

    _print_report(report, args.execute)
    return 0


if __name__ == "__main__":
    sys.exit(main())
