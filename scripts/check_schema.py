"""Check the database actually has every table and column the models declare.

`db.create_all()` creates missing *tables* but never alters an existing one.
So a column added to a model months after its table was first created is
present in the code and absent from the database, and nothing says so until
a query touches it in production. That is the failure this catches.

    python scripts/check_schema.py             # report only, changes nothing
    python scripts/check_schema.py --fix       # add the missing columns
    python scripts/check_schema.py --fix --yes # ...without the confirmation

Exit code is 0 when the schema matches, 1 when it does not - so it can gate a
deployment.

What --fix will and will not do
-------------------------------
It adds missing tables (via create_all) and missing columns (ALTER TABLE ADD
COLUMN). It never drops, renames, retypes or reorders anything, and it
refuses to add a NOT NULL column with no default, because there is no honest
value to give the rows already in the table. Anything it will not do itself
is reported for a human to decide, rather than guessed at.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import CompileError  # noqa: E402

from src.app import create_app  # noqa: E402
from src.extensions import db  # noqa: E402
import src.models  # noqa: E402,F401  (registers every model on the metadata)


def _column_ddl(column, dialect) -> str:
    """The type this column needs, in the connected database's own dialect."""
    return column.type.compile(dialect=dialect)


def _default_clause(column) -> str:
    """A DEFAULT clause for a column that cannot be left NULL.

    Only literal defaults are usable here: a Python-side default (a callable
    like `get_current_time`) means nothing to ALTER TABLE, and the rows
    already in the table need a value the database itself can supply.
    """
    default = getattr(column, 'server_default', None)
    if default is not None and getattr(default, 'arg', None) is not None:
        return f' DEFAULT {default.arg}'

    default = getattr(column, 'default', None)
    if default is not None and not getattr(default, 'is_callable', False):
        value = getattr(default, 'arg', None)
        if isinstance(value, bool):
            return f' DEFAULT {1 if value else 0}'
        if isinstance(value, (int, float)):
            return f' DEFAULT {value}'
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f" DEFAULT '{escaped}'"
    return ''


def audit():
    """Every table and column the models expect but the database lacks."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    missing_tables = []
    missing_columns = []

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            missing_tables.append(table.name)
            continue

        present = {c['name'] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in present:
                missing_columns.append((table, column))

    return missing_tables, missing_columns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fix', action='store_true',
                        help='add the missing tables and columns')
    parser.add_argument('--yes', action='store_true',
                        help='skip the confirmation prompt when fixing')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print(f'Database: {app.config["SQLALCHEMY_DATABASE_URI"]}\n')

        missing_tables, missing_columns = audit()
        dialect = db.engine.dialect

        if not missing_tables and not missing_columns:
            tables = len(db.metadata.sorted_tables)
            columns = sum(len(t.columns) for t in db.metadata.sorted_tables)
            print(f'Schema matches the models: {tables} tables, {columns} columns.')
            return 0

        if missing_tables:
            print(f'{len(missing_tables)} table(s) missing:')
            for name in missing_tables:
                print(f'  - {name}')

        unsafe = []
        if missing_columns:
            print(f'\n{len(missing_columns)} column(s) missing:')
            for table, column in missing_columns:
                try:
                    type_sql = _column_ddl(column, dialect)
                except CompileError:
                    type_sql = '?'
                default = _default_clause(column)
                nullable = '' if column.nullable else ' NOT NULL'
                note = ''
                if not column.nullable and not default:
                    note = '   <-- NOT NULL with no default; needs a human'
                    unsafe.append((table.name, column.name))
                print(f'  - {table.name}.{column.name} {type_sql}{nullable}{default}{note}')

        if not args.fix:
            print('\nReport only. Re-run with --fix to apply.')
            return 1

        if unsafe:
            print(f'\nRefusing to fix: {len(unsafe)} column(s) are NOT NULL with no '
                  'default, and the rows already in those tables have no honest '
                  'value to receive. Add them by hand, with the value they should '
                  'take, then re-run.')
            return 1

        if not args.yes:
            reply = input('\nApply these changes? [y/N] ').strip().lower()
            if reply != 'y':
                print('Nothing was changed.')
                return 1

        if missing_tables:
            db.create_all()
            print(f'\nCreated {len(missing_tables)} table(s).')

        for table, column in missing_columns:
            type_sql = _column_ddl(column, dialect)
            nullable = '' if column.nullable else ' NOT NULL'
            statement = (f'ALTER TABLE {table.name} ADD COLUMN '
                         f'{column.name} {type_sql}{nullable}{_default_clause(column)}')
            db.session.execute(text(statement))
            print(f'  {statement}')
        if missing_columns:
            db.session.commit()
            print(f'\nAdded {len(missing_columns)} column(s).')

        still_tables, still_columns = audit()
        if still_tables or still_columns:
            print('\nSchema still does not match after fixing - see above.')
            return 1
        print('\nSchema now matches the models.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
