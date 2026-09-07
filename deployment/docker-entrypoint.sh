#!/bin/sh
# deployment/docker-entrypoint.sh
#
# Brings the database up to date before the web container starts serving.
#
# The deploy provisions an empty Postgres, so a container that went straight to
# gunicorn would serve a correct application with no schema and no rows. Both
# steps below are safe to repeat: migrations are versioned, and the seed only
# populates a database that is still empty, so redeploys leave live data alone.
set -e

echo "[entrypoint] applying database migrations"
flask db upgrade || alembic upgrade head

# --if-empty seeds the first boot and exits quietly on every later one, so a
# redeploy never duplicates rows or overwrites data entered since launch.
if [ -f "instance/management.db" ]; then
    echo "[entrypoint] seeding from instance/management.db if the target is empty"
    python scripts/migrate_sqlite_to_postgres.py --if-empty
else
    echo "[entrypoint] no seed database present; skipping"
fi

echo "[entrypoint] starting: $*"
exec "$@"
