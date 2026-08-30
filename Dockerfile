# Cold Storage application image.
#
# Repository layout (this matters for every path below):
#   /app/requirements.txt
#   /app/docker-entrypoint.sh
#   /app/coldstorage_project/manage.py                      <- Django project root
#   /app/coldstorage_project/coldstorage_project/settings.py
#   /app/coldstorage_project/coldstorage_project/wsgi.py    <- coldstorage_project.wsgi:application
#   /app/coldstorage_project/coldstorage/                   <- the app
#
# manage.py is NOT at /app/manage.py, so every command has to run from
# /app/coldstorage_project.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/coldstorage_project \
    DJANGO_SETTINGS_MODULE=coldstorage_project.settings

# Log to stdout/stderr only; a log file inside a container is a dead end.
ENV DJANGO_LOG_FILE=""

WORKDIR /app

# Install dependencies first so this layer is cached independently of the code.
# psycopg[binary] ships wheels, so no libpq-dev/gcc are needed.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/

# Collect static files into STATIC_ROOT (/app/coldstorage_project/staticfiles)
# at build time; WhiteNoise serves them from there at runtime. The throwaway
# key exists only because settings must import with DEBUG off - collectstatic
# signs nothing.
RUN DJANGO_DEBUG=0 DJANGO_SECRET_KEY="build-time-placeholder-not-used-at-runtime" \
    python /app/coldstorage_project/manage.py collectstatic --noinput --clear

# Run as a non-root user. The writable directories are created and chowned in
# the image so that named volumes mounted over them inherit that ownership.
RUN useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/coldstorage_project/media /app/data \
 && chmod +x /app/docker-entrypoint.sh \
 && chown -R appuser:appuser /app

USER appuser
WORKDIR /app/coldstorage_project

EXPOSE 8000

# The entrypoint migrates, then execs CMD. gunicorn - not `runserver`, which is
# the development server and must never serve real traffic.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "coldstorage_project.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
