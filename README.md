# flux-datalist

# 🧊 Cold Storage Data Acquisition Web App

[![CI](https://github.com/ethanbissbort/flux-datalist/actions/workflows/ci.yml/badge.svg)](https://github.com/ethanbissbort/flux-datalist/actions/workflows/ci.yml)

A Django-based, modular database for managing and archiving critical data for long-term cold
storage — operating systems, software, games, media, and scientific archives.

---

## 🚀 Features

- Hierarchical categories with cycle protection
- Size estimation and per-category storage breakdowns
- Tagging (shared between the web UI and the API)
- File tracking with MD5/SHA-256 checksums and integrity verification
- Storage-provider cost estimation and comparison
- Batch operations over filtered item sets
- REST API with search, filtering, ordering and pagination
- Export to CSV, JSON and Excel; bulk import from JSON
- Dockerized, running gunicorn behind a non-root user

---

## 📦 Categories Covered

- Operating Systems
- Software Images
- Games (PC, console, mods)
- TV Shows / Movies
- YouTube Channels / Reddit Subs
- Scientific Literature / Books / Magazines

---

## 🔧 Quick Start (Docker)

```bash
git clone https://github.com/ethanbissbort/flux-datalist.git
cd flux-datalist
docker compose up --build
```

The app is then on <http://localhost:8000>. The entrypoint runs migrations on start; SQLite data
and uploaded media live on named volumes, so they survive `docker compose down`.

Defaults in `docker-compose.yml` are for local development (`DJANGO_DEBUG=1`). For anything
real, turn debug off and supply a key — with debug off the container refuses to start without one:

```bash
DJANGO_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))') \
DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=coldstorage.example.com \
docker compose up --build -d
```

PostgreSQL instead of SQLite: set `DJANGO_DB_ENGINE=postgresql` plus `DJANGO_DB_NAME`,
`DJANGO_DB_USER`, `DJANGO_DB_PASSWORD`, `DJANGO_DB_HOST`, `DJANGO_DB_PORT`. The driver is already
in the image.

## 🔧 Quick Start (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd coldstorage_project
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## ✅ Tests

```bash
cd coldstorage_project
python manage.py test coldstorage
```

The suite is a regression net over the defects in [`AUDIT.md`](AUDIT.md). `RouteSmokeTests` walks
the URLconf and asserts that no registered route returns a server error — the single cheapest
guard against the class of breakage that audit found.

Also worth running before a deploy:

```bash
python manage.py check --deploy
```

**Note:** run the suite with `DJANGO_DEBUG=1` (the default in a source checkout). With debug off
the settings enable `SECURE_SSL_REDIRECT`, so every test-client request is answered with a 301 and
35 tests fail with a misleading error.

CI runs all of this on every push and pull request — the test suite, `check`, `check --deploy`, a
missing-migration check, and a Docker build plus container smoke test. See
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## 🌐 API

Browsable at `/api/`. Reads are open; writes require authentication (session, or a token from
`POST /api/auth/token/`).

| Endpoint | Purpose |
|---|---|
| `/api/items/` | Data items (CRUD) |
| `/api/categories/` | Categories (CRUD) |
| `/api/tags/` | Tags, with `popular/` and `by_category/` |
| `/api/files/` | Tracked files, with `verify/` and `calculate_checksum/` |
| `/api/providers/` | Storage providers, with `compare/` and `calculate_estimate/` |
| `/api/costs/` | Cost estimates, with `summary/` and `comparison/` |

**Search / filter / order:**

```bash
curl "http://localhost:8000/api/items/?search=linux"          # name, description, tag names
curl "http://localhost:8000/api/items/?category=3&status=stored"
curl "http://localhost:8000/api/items/?ordering=-size_estimate_gb"
```

**Export** — note the parameter is `export_format`, **not** `format`. DRF reserves `format` for
its own content negotiation and will return 404 for a value it has no renderer for:

```bash
curl "http://localhost:8000/api/items/export/?export_format=csv"   > items.csv
curl "http://localhost:8000/api/items/export/?export_format=excel" > items.xlsx
curl "http://localhost:8000/api/items/export/?export_format=json"  > items.json
```

**Tagging** — supply either a comma-separated string or existing tag IDs, not both:

```bash
curl -X POST http://localhost:8000/api/items/ \
  -H 'Content-Type: application/json' \
  -d '{"name":"Debian 12","category":1,"tags":"linux, iso"}'
```

**Batch operations:**

```bash
curl -X POST http://localhost:8000/api/items/batch_operation/ \
  -H 'Content-Type: application/json' \
  -d '{"operation":"update_status","status":"stored","item_ids":[1,2,3]}'
```

Supported operations: `update_status`, `update_priority`, `update_category`, `add_tags`,
`remove_tags`, `set_tags`, `delete`.

---

## 📥 Importing

`POST /import-json/` (signed in) accepts a JSON array of objects:

```json
[
  {
    "name": "Debian 12",
    "category": "Operating Systems",
    "tags": "linux, iso",
    "size_estimate_gb": 4.5,
    "priority": "high",
    "status": "planned"
  }
]
```

Unknown categories are created automatically. Each row is imported in its own transaction, so a
bad row rolls back only itself. Sample files are in `coldstorage_project/sample_data/`.

---

## ⚙️ Configuration

All settings are environment-driven.

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `0`, but see below | Never enable in production |
| `DJANGO_SECRET_KEY` | generated per checkout | **Required** when `DJANGO_DEBUG=0` — startup fails without it |
| `DJANGO_ALLOWED_HOSTS` | localhost set | Comma-separated |
| `DJANGO_DB_ENGINE` | `sqlite3` | or `postgresql` |
| `COLDSTORAGE_ALLOWED_STORAGE_ROOTS` | `[MEDIA_ROOT]` | Directories `storage_path` may read from |

`DJANGO_DEBUG` defaults to off **except** in a git working tree with the variable unset, which is
treated as a developer machine so `manage.py` works in a fresh checkout. Images built from the
Dockerfile exclude `.git` and therefore always default to off. The consequence worth knowing: a
server deployed by `git clone` with no environment variables set still comes up with debug on. It
warns loudly at startup, and the secret key is generated per checkout rather than shared, but set
`DJANGO_DEBUG=0` explicitly on any deployment.

With `DJANGO_DEBUG=0`, HTTPS redirect, HSTS and secure session/CSRF cookies switch on
automatically.

---

## 📋 Project Health

[`AUDIT.md`](AUDIT.md) is a full audit of the repository, verified by execution. It documents 30
findings and is the authoritative record of what was broken and why. The critical and high-severity
items are fixed and covered by tests; the file retains the original findings so the reasoning
behind each fix stays traceable.

---

## 📄 License

MIT — see [LICENSE](LICENSE).
