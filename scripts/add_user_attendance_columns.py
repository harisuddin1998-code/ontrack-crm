"""Add the sign-in timekeeping columns to `users` on an existing database.

`db.create_all()` creates missing tables but never alters an existing one, so
new columns on a table that is already there have to be added explicitly.
These three back the greeting a user sees when they land:

    last_login_day     the Pakistan-time date of their last first-sign-in
    last_late_login    the last date they arrived after 10:30
    late_login_streak  consecutive late days, cleared by any on-time day

Existing users start with no history and a zero streak - nobody is called
habitual on the strength of mornings that were never recorded.

Safe to run more than once: each column is checked first and skipped if it is
already present.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from src.app import create_app  # noqa: E402
from src.extensions import db  # noqa: E402

TABLE = 'users'
COLUMNS = {
    'last_login_day': 'DATE',
    'last_late_login': 'DATE',
    'late_login_streak': 'INTEGER NOT NULL DEFAULT 0',
}


def main() -> int:
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)

        if TABLE not in inspector.get_table_names():
            print(f'{TABLE} does not exist yet - create_all will build it with the columns.')
            db.create_all()
            return 0

        existing = {c['name'] for c in inspector.get_columns(TABLE)}
        added = 0
        for column, definition in COLUMNS.items():
            if column in existing:
                print(f'{TABLE}.{column} already present - nothing to do.')
                continue
            db.session.execute(text(f'ALTER TABLE {TABLE} ADD COLUMN {column} {definition}'))
            print(f'Added {TABLE}.{column}.')
            added += 1

        if added:
            db.session.commit()

        # Picks up the suggestions tables at the same time, so a database
        # upgraded with this script is ready for the whole release.
        db.create_all()
        print('create_all() run - any new tables are in place.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
