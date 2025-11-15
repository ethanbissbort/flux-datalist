# Cold Storage Data Acquisition Web App - Project Context

## Project Overview

This is a Django-based web application for managing and archiving critical data for long-term cold storage. The system provides a modular database for tracking operating systems, software, games, media, and scientific archives.

## Tech Stack

- **Framework**: Django 4.2+
- **API**: Django REST Framework 3.14+
- **Database**: SQLite (default Django DB)
- **Deployment**: Docker & Docker Compose
- **Language**: Python 3.x

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
│   │   └── migrations/           # Database migrations
│   └── manage.py                 # Django management script
├── Dockerfile                    # Docker configuration
├── docker-compose.yml            # Docker Compose setup
├── requirements.txt              # Python dependencies
├── generate_django_files.py      # Code generation utility
└── setup_project.py              # Project setup script
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
docker-compose up --build
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
python manage.py test
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
- Current working branch: `claude/create-claude-md-01RNqDFeeRCkdm1oWB6CQegT`

## Notes for Claude Code

- The project uses Django's default SQLite database
- Static files and media handling may need configuration for production
- The app is designed to be modular and extensible
- Follow Django best practices for models, views, and URL routing
- Use Django REST Framework conventions for API endpoints
- Always run migrations after model changes
- Test changes both via web interface and API endpoints
