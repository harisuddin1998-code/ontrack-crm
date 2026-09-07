"""Add `synced_from_po` to security_briefing_data on an existing database.

`db.create_all()` creates missing tables but never alters an existing one, so
a new column on a table that already exists has to be added explicitly.

Safe to run more than once: it checks for the column first and does nothing
if it is already there.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from src.app import create_app  # noqa: E402
from src.extensions import db  # noqa: E402

TABLE = 'security_briefing_data'
COLUMN = 'synced_from_po'


def main() -> int:
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)

        if TABLE not in inspector.get_table_names():
            print(f'{TABLE} does not exist yet - create_all will build it with the column.')
            return 0

        columns = {c['name'] for c in inspector.get_columns(TABLE)}
        if COLUMN in columns:
            print(f'{TABLE}.{COLUMN} already present - nothing to do.')
            return 0

        # Existing briefings pre-date automatic creation, so they are marked
        # as manual (0) rather than being claimed by an installation that
        # never raised them.
        db.session.execute(text(
            f'ALTER TABLE {TABLE} ADD COLUMN {COLUMN} BOOLEAN NOT NULL DEFAULT 0'))
        db.session.commit()
        print(f'Added {TABLE}.{COLUMN} (existing rows marked as manual).')

        db.create_all()
        print('create_all() run - any new tables are in place.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
