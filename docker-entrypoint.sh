#!/bin/sh
#
# Container entrypoint.
#
# Migrations run here, at container start, not at image build time: baking a
# migrated database into the image produces an image with somebody else's data
# in it and cannot work at all against an external database.
#
# Set DJANGO_SKIP_MIGRATIONS=1 when several replicas start at once and a single
# release job owns the migrations instead.
set -e

cd /app/coldstorage_project

if [ "${DJANGO_SKIP_MIGRATIONS:-0}" != "1" ]; then
    echo "==> Applying database migrations"
    python manage.py migrate --noinput
fi

# Static files are collected into STATIC_ROOT during the image build and served
# by WhiteNoise. Re-collect only if asked (e.g. STATIC_ROOT on a volume).
if [ "${DJANGO_COLLECTSTATIC:-0}" = "1" ]; then
    echo "==> Collecting static files"
    python manage.py collectstatic --noinput
fi

echo "==> Starting: $*"
exec "$@"
