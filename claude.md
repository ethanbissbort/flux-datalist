# Cold Storage Data Acquisition Web App - Project Context

## Project Overview

This is a Django-based web application for managing and archiving critical data for long-term cold storage. The system provides a modular database for tracking operating systems, software, games, media, and scientific archives.

## Tech Stack

- **Framework**: Django 5.2.x (pinned `>=5.2,<5.3`)
- **API**: Django REST Framework 3.18.x, with `django-filter` for query-string filtering
- **Database**: SQLite by default; PostgreSQL via `DJANGO_DB_ENGINE=postgresql` (psycopg 3)
- **Deployment**: Docker & Docker Compose, gunicorn + WhiteNoise, non-root user
- **Language**: Python 3.11

## Project Structure

```
flux-datalist/
├── coldstorage_project/          # Main Django project directory
│   ├── coldstorage_project/      # Project settings and config
│   │   ├── settings.py           # Django settings
│   │   ├── urls.py               # Root URL configuration
│   │   ├── wsgi.py               # WSGI config
│   │   └── asgi.py               # ASGI config
│   ├── coldstorage/              # Main app for cold storage management
│   │   ├── models.py             # Database models
│   │   ├── views.py              # View logic
│   │   ├── serializers.py        # DRF serializers
│   │   ├── urls.py               # App URL configuration
│   │   ├── admin.py              # Django admin config
│   │   ├── forms.py              # Web forms
│   │   ├── services.py           # Import/export/batch business logic
│   │   ├── tests.py              # Regression suite (see AUDIT.md)
│   │   ├── templates/            # index, dashboard, registration/login
│   │   └── migrations/           # Database migrations
│   ├── sample_data/              # Seed JSON in the app's import format
│   └── manage.py                 # Django management script
├── AUDIT.md                      # Repository audit — authoritative defect record
├── Dockerfile                    # Docker configuration
├── docker-compose.yml            # Docker Compose setup
├── docker-entrypoint.sh          # Migrates, then execs gunicorn
├── requirements.txt              # Python dependencies
└── setup_project.py              # Seeds initial categories
```

## Key Features

- **Modular Categories**: Hierarchical organization of different data types
- **Size Estimation**: Calculate storage requirements for each item
- **Web Frontend**: Simple interface for adding/viewing items
- **REST API**: Full API access via Django REST Framework
- **Import/Export**: CSV/JSON capabilities for data portability
- **Dockerized**: Easy deployment with Docker support

## Data Categories

The system manages the following types of data:
- Operating Systems
- Software Images
- Games (PC, console, mods)
- TV Shows / Movies
- YouTube Channels / Reddit Subs
- Scientific Literature / Books / Magazines

## Development Setup

### Using Docker (Recommended)

```bash
docker compose up --build
```

The app will be available at `http://localhost:8000`

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations
cd coldstorage_project
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver
```

## Common Tasks

### Running Migrations

```bash
cd coldstorage_project
python manage.py makemigrations
python manage.py migrate
```

### Creating a Superuser

```bash
cd coldstorage_project
python manage.py createsuperuser
```

### Running Tests

```bash
cd coldstorage_project
python manage.py test coldstorage
```

Every test maps to a finding in `AUDIT.md`. `RouteSmokeTests` walks the URLconf and asserts no
route 5xxs — run it before any commit that touches views, serializers or models.

Before deploying:

```bash
python manage.py check --deploy   # must report zero issues
```

### Accessing Django Admin

Navigate to `http://localhost:8000/admin` after starting the server.

## Important Files

- **coldstorage_project/coldstorage/models.py**: Core data models
- **coldstorage_project/coldstorage/views.py**: View logic and request handling
- **coldstorage_project/coldstorage/serializers.py**: API serialization
- **coldstorage_project/coldstorage_project/settings.py**: Project configuration
- **requirements.txt**: Python package dependencies

## Git Workflow

- Main branch: `main`
- Feature branches: Use `claude/*` prefix for AI-assisted development

## Invariants — read before changing these

These are not style preferences. Each one is a defect that reached `main` and is documented in
`AUDIT.md`; a regression test guards each.

1. **`DataItem` has no `tags` field.** Tags live on the `tag_set` many-to-many relation;
   `tags_old` is a deprecated free-text column kept only for migration history. Never pass
   `tags=` to `DataItem.objects.create()` and never put `'tags'` in a `ModelSerializer.Meta.fields`
   or an admin `fieldsets`. Use `add_tags_from_string()`, `get_tags_display()`, `get_tags_list()`,
   or query `tag_set__name`. Propagating a rename to *every* call site is the whole lesson here.

2. **Checksum verification must never write a recalculated digest to the stored columns.**
   `verify_checksum()` compares against the stored baseline and persists only `status`,
   `last_verified_at` and `verification_error`. Overwriting the baseline destroys the evidence of
   corruption and makes a re-verify report the file clean. `calculate_checksums()` is the one
   deliberate re-baseline path.

3. **Category parents must go through `would_create_cycle()`.** The model, the form and the
   serializer all call it. An unguarded parent write persists a cycle and then hangs the worker
   forever in `get_full_path()`. Both traversal methods are depth-capped for already-poisoned rows.

4. **`storage_path` is attacker-controlled.** Reads are confined to
   `COLDSTORAGE_ALLOWED_STORAGE_ROOTS` (default `[MEDIA_ROOT]`) via realpath + `commonpath`.
   Do not add a code path that opens it directly.

5. **The export query parameter is `export_format`, not `format`.** DRF reserves `format`
   (`URL_FORMAT_OVERRIDE`) and raises 404 for an unknown value before the view body runs.

6. **Do not forward `request.data` as `**kwargs`** to a function that also takes one of those keys
   positionally — that is a guaranteed `TypeError`.

7. **Web writes require auth.** `index` (POST) and `import_json` are gated to match the API's
   `IsAuthenticatedOrReadOnly`. Reads stay open.

8. **Vue templates must sit inside `{% verbatim %}`.** Django renders `{{ }}` server-side first and
   will otherwise silently blank every Vue binding.

## Notes for Claude Code

- Static files are collected at image build and served by WhiteNoise
- `DEBUG` defaults to **off**; a missing `DJANGO_SECRET_KEY` with debug off is a hard startup error
- The app is designed to be modular and extensible
- Follow Django best practices for models, views, and URL routing
- Use Django REST Framework conventions for API endpoints
- Always run migrations after model changes
- Test changes both via web interface and API endpoints
