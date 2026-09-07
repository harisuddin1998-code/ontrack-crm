#!/usr/bin/env python3
"""
Copy the SQLite working database into the deployed PostgreSQL database.

The deploy provisions an empty Postgres and runs the Alembic migrations, which
build the schema and nothing else. Every row the business actually uses still
lives in the SQLite file the application was developed against, so a fresh
deployment comes up correct but empty. This script moves those rows across.

Run it on the server, from the project directory, once the stack is up:

    docker compose cp instance/management.db web:/app/instance/management.db
    docker compose exec web python scripts/migrate_sqlite_to_postgres.py --dry-run
    docker compose exec web python scripts/migrate_sqlite_to_postgres.py

The database is customer data and this repository is public, so the SQLite file
must be copied to the server out of band - never committed, never attached to
an issue.

Tables are written in foreign-key order, taken from the models themselves
rather than a hand-maintained list, so a table is always populated after
whatever it references. Primary keys are preserved: rows point at each other by
id, and renumbering them on the way in would quietly break those references.
Postgres sequences are then advanced past the highest id in each table, because
inserting explicit ids leaves a sequence still sitting at 1 and the next insert
the application attempts would collide with existing data.
"""
import argparse
import os
import sys
from typing import Iterable, List, Tuple

# The application package lives one level up from scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, insert, select, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

# Importing the models registers every table on the shared metadata; without
# this the metadata is empty and there is nothing to copy.
import src.models  # noqa: F401,E402
from src.extensions import db  # noqa: E402

BATCH = 1000


def _sqlite_url(path: str) -> str:
    if not os.path.exists(path):
        sys.exit("SQLite database not found: %s" % path)
    return "sqlite:///%s" % os.path.abspath(path).replace("\\", "/")


def _target_url(explicit: str = None) -> str:
    url = explicit or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("No target database. Pass --target or set DATABASE_URL.")
    if url.startswith("sqlite"):
        sys.exit("Target is SQLite (%s). This copies *into* Postgres." % url)
    return url


def _table_names(source: Engine) -> set:
    """Tables that actually exist in the source file."""
    with source.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        return {r[0] for r in rows}


def _plan(source: Engine) -> List:
    """Model tables that exist in the source, in foreign-key-safe order."""
    present = _table_names(source)
    return [t for t in db.metadata.sorted_tables if t.name in present]


def _select(tables: List, wanted: str) -> List:
    """Narrow the plan to the named tables, keeping foreign-key order.

    A subset is how a single area is moved into a database that is already
    live - the annual recovery sheets, say, into a server whose users, POs and
    complaints must not be touched. Copying everything into a running system
    duplicates all of it.
    """
    names = [n.strip() for n in wanted.split(",") if n.strip()]
    by_name = {t.name: t for t in tables}

    unknown = [n for n in names if n not in by_name]
    if unknown:
        sys.exit("Not in the source database: " + ", ".join(unknown)
                 + ". Available: " + ", ".join(sorted(by_name)))

    chosen = [t for t in tables if t.name in set(names)]

    # A table whose parent is left behind will fail on the foreign key, or
    # worse, land pointing at whatever row already holds that id on the
    # target. Named here rather than discovered halfway through a copy.
    picked = {t.name for t in chosen}
    dangling = []
    for table in chosen:
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent not in picked and parent != table.name:
                dangling.append("%s -> %s" % (table.name, parent))
    if dangling:
        print("WARNING: these reference tables that are not being copied:")
        for d in sorted(set(dangling)):
            print("  %s" % d)
        print("The rows will only be correct if the target already holds the")
        print("matching parent rows with the same ids.")
        print("")

    return chosen


def _count(engine: Engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(
            select(text("count(*)")).select_from(table)
        ).scalar_one()


def _copy_table(source: Engine, target: Engine, table) -> Tuple[int, int]:
    """Copy one table. Returns (rows read, rows written)."""
    with source.connect() as src_conn:
        rows = [dict(r) for r in src_conn.execute(select(table)).mappings()]

    if not rows:
        return 0, 0

    written = 0
    with target.begin() as dst_conn:
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            dst_conn.execute(insert(table), chunk)
            written += len(chunk)
    return len(rows), written


def _reset_sequences(target: Engine, tables: Iterable) -> List[str]:
    """
    Advance each identity sequence past the ids just inserted.

    Rows were written with their original primary keys, so every sequence is
    still where it started and the application's next insert would raise a
    duplicate key error on a table that looks perfectly healthy.
    """
    done = []
    with target.begin() as conn:
        for table in tables:
            for col in table.primary_key.columns:
                if not col.autoincrement or not str(col.type).lower().startswith(("integer", "bigint")):
                    continue
                seq = conn.execute(
                    text("SELECT pg_get_serial_sequence(:t, :c)"),
                    {"t": table.name, "c": col.name},
                ).scalar()
                if not seq:
                    continue
                conn.execute(
                    text(
                        "SELECT setval(:s, COALESCE((SELECT MAX(%s) FROM %s), 0) + 1, false)"
                        % (col.name, table.name)
                    ),
                    {"s": seq},
                )
                done.append("%s.%s" % (table.name, col.name))
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="instance/management.db",
                    help="SQLite file to read (default: instance/management.db)")
    ap.add_argument("--target", default=None,
                    help="Target URL (default: $DATABASE_URL)")
    ap.add_argument("--tables", default=None,
                    help="Comma-separated tables to copy instead of all of "
                         "them, e.g. the annual recovery sheets on their own. "
                         "Foreign-key order is kept, and anything referencing "
                         "a table left behind is reported first.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would be copied and change nothing")
    ap.add_argument("--force", action="store_true",
                    help="Copy even though the target already holds rows")
    ap.add_argument("--if-empty", action="store_true",
                    help="Seed an empty target, and succeed quietly if it "
                         "already holds rows. Lets container start-up call "
                         "this on every boot and only seed the first one.")
    args = ap.parse_args()

    source = create_engine(_sqlite_url(args.source))
    target = create_engine(_target_url(args.target))

    tables = _plan(source)
    if not tables:
        sys.exit("No model tables found in %s." % args.source)

    if args.tables:
        tables = _select(tables, args.tables)
        if not tables:
            sys.exit("No tables selected.")

    print("source : %s" % args.source)
    print("target : %s" % target.url.render_as_string(hide_password=True))
    print("tables : %d\n" % len(tables))

    # A target that already holds data is the dangerous case: re-running would
    # duplicate every row, so it takes an explicit --force. A dry run reads the
    # source only and must not need the target to be reachable at all.
    if not args.dry_run:
        occupied = [(t.name, _count(target, t)) for t in tables]
        occupied = [(n, c) for n, c in occupied if c]
        if occupied and args.if_empty:
            print("Target already holds data (%s: %d rows and %d other tables); "
                  "nothing to seed." % (occupied[0][0], occupied[0][1], len(occupied) - 1))
            return 0
        if occupied and not args.force:
            print("Target is not empty:")
            for n, c in occupied[:10]:
                print("  %-40s %d rows" % (n, c))
            print("\nRe-running would duplicate these. Pass --force if that is intended.")
            return 1

    total_read = total_written = 0
    for table in tables:
        n = _count(source, table)
        if args.dry_run:
            if n:
                print("  would copy %-40s %d rows" % (table.name, n))
            total_read += n
            continue

        read, written = _copy_table(source, target, table)
        total_read += read
        total_written += written
        if read:
            flag = "" if read == written else "  <-- MISMATCH"
            print("  %-40s %d -> %d%s" % (table.name, read, written, flag))

    if args.dry_run:
        print("\nDry run: %d rows would be copied. Nothing was changed." % total_read)
        return 0

    seqs = _reset_sequences(target, tables)
    print("\ncopied    : %d rows read, %d written" % (total_read, total_written))
    print("sequences : %d advanced past the inserted ids" % len(seqs))

    if total_read != total_written:
        print("\nRow counts differ - investigate before using this database.")
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
