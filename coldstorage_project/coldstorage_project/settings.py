"""
Django settings for coldstorage_project project.

The configuration is environment driven and the *secure* configuration is the
default: nothing in this file has to be edited to deploy, and a deployment that
forgets to set a variable fails loudly instead of quietly serving with debug
turned on and a published secret key.

Environment variables
---------------------
DJANGO_DEBUG
    ``1/true/yes/on`` turns debug on, anything else turns it off.  Debug is OFF
    unless it is asked for; the single exception is an unconfigured source
    checkout (a ``.git`` working tree with no ``DJANGO_DEBUG`` in the
    environment), which is a developer's machine and defaults to debug on.
    Images built from the Dockerfile do not ship ``.git`` and therefore always
    default to debug off.
DJANGO_SECRET_KEY
    Required whenever DEBUG is off.  Missing => ImproperlyConfigured.
DJANGO_ALLOWED_HOSTS
    Comma separated host names.  Defaults to the local development hosts.
DJANGO_CSRF_TRUSTED_ORIGINS
    Comma separated ``scheme://host[:port]`` origins (needed behind a proxy
    that terminates TLS on a different host name).
DJANGO_DB_ENGINE
    ``sqlite3`` (default), ``postgresql``, or a full dotted backend path.
DJANGO_DB_NAME / DJANGO_DB_USER / DJANGO_DB_PASSWORD / DJANGO_DB_HOST /
DJANGO_DB_PORT / DJANGO_DB_CONN_MAX_AGE
    Database connection details (the legacy ``DB_*`` spellings are still read).
    For sqlite, ``DJANGO_DB_NAME`` is the path to the database file.
DJANGO_SECURE_HSTS_SECONDS
    HSTS max-age used when DEBUG is off.  Defaults to one year.
DJANGO_LOG_LEVEL / DJANGO_LOG_FILE
    Log level for the project loggers and the path of the log file (set
    ``DJANGO_LOG_FILE=`` empty to log to the console only).
COLDSTORAGE_ALLOWED_STORAGE_ROOTS
    ``os.pathsep`` separated absolute directories that the app is allowed to
    read files from.  Defaults to ``[MEDIA_ROOT]``.
"""

import os
import warnings
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# The repository root (the directory that holds manage.py's parent).
REPO_DIR = BASE_DIR.parent


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
_TRUE_VALUES = {'1', 'true', 'yes', 'on'}
_FALSE_VALUES = {'0', 'false', 'no', 'off', ''}


def _env(*names, default=None):
    """First non-empty value among ``names``, else ``default``."""
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _env_bool(*names, default=False):
    value = _env(*names)
    if value is None:
        return default
    lowered = value.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    allowed = sorted((_TRUE_VALUES | _FALSE_VALUES) - {''})
    raise ImproperlyConfigured(f'{names[0]} must be one of {allowed}, got {value!r}.')


def _env_list(*names, default=None, separator=','):
    value = _env(*names)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(separator) if item.strip()]


def _env_int(*names, default=0):
    value = _env(*names)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f'{names[0]} must be an integer, got {value!r}.') from exc


# ---------------------------------------------------------------------------
# Debug / secret key / hosts
# ---------------------------------------------------------------------------
# DEBUG comes from the environment and defaults to False.  The only thing that
# can flip that default is an unconfigured source checkout: running out of a
# git working tree with nothing set at all is a developer machine, not a
# deployment.  Deployments (containers built from the Dockerfile, which
# excludes .git, or any environment that sets DJANGO_DEBUG explicitly) always
# get DEBUG=False unless they deliberately ask for it.
# An explicitly set DJANGO_DEBUG always wins, including when it is set to an
# empty value (which means "off"); only a completely absent variable falls back
# to the source-checkout default.
_IS_SOURCE_CHECKOUT = (REPO_DIR / '.git').exists()
if 'DJANGO_DEBUG' in os.environ:
    DEBUG = _env_bool('DJANGO_DEBUG', default=False)
else:
    DEBUG = _IS_SOURCE_CHECKOUT

if DEBUG and 'DJANGO_DEBUG' not in os.environ:
    # DEBUG was inferred from the presence of a source checkout rather than
    # asked for. That is right on a developer machine and wrong on a server
    # someone deployed with `git clone`, so say so loudly.
    warnings.warn(
        'DEBUG is on because this is a source checkout and DJANGO_DEBUG is '
        'unset. Set DJANGO_DEBUG=0 (and DJANGO_SECRET_KEY) for any deployment.',
        RuntimeWarning,
        stacklevel=2,
    )


def _development_secret_key() -> str:
    """
    Return a random key for local development, persisted across restarts.

    Deliberately not a constant checked into the repository: a published key
    lets anyone forge sessions and password-reset tokens, and it only takes one
    misconfigured deployment for that to matter. The key is cached in a
    gitignored file so the autoreloader does not log developers out on every
    restart; if it cannot be written we fall back to an ephemeral key rather
    than to a shared one.
    """
    key_file = REPO_DIR / '.dev-secret-key'
    try:
        if key_file.is_file():
            cached = key_file.read_text().strip()
            if cached:
                return cached
    except OSError:
        pass

    generated = secrets.token_urlsafe(64)
    try:
        key_file.write_text(generated + '\n')
        key_file.chmod(0o600)
    except OSError:
        pass  # Read-only checkout: an ephemeral key still beats a shared one.
    return generated


# SECURITY WARNING: keep the secret key used in production secret!
# With DEBUG off a real key must be supplied; there is no fallback.
SECRET_KEY = _env('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = _development_secret_key()
    else:
        raise ImproperlyConfigured(
            'DJANGO_SECRET_KEY is not set. Generate one with '
            '`python -c "import secrets; print(secrets.token_urlsafe(64))"` and '
            'export it as DJANGO_SECRET_KEY, or set DJANGO_DEBUG=1 for local '
            'development (which generates a throwaway key).'
        )

ALLOWED_HOSTS = _env_list(
    'DJANGO_ALLOWED_HOSTS',
    default=['localhost', '127.0.0.1', '0.0.0.0', '[::1]'],
)

CSRF_TRUSTED_ORIGINS = _env_list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[])


# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'django_filters',
    'coldstorage',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves everything under STATIC_ROOT without a separate web server.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'coldstorage_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / 'coldstorage' / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'coldstorage_project.wsgi.application'


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# The backend is chosen by an explicit variable, independently of DEBUG and of
# any "environment name": local development can talk to PostgreSQL and a
# deployment can run on sqlite if that is really what it wants.
_DB_ENGINE_ALIASES = {
    'sqlite': 'django.db.backends.sqlite3',
    'sqlite3': 'django.db.backends.sqlite3',
    'postgres': 'django.db.backends.postgresql',
    'postgresql': 'django.db.backends.postgresql',
    'mysql': 'django.db.backends.mysql',
    'oracle': 'django.db.backends.oracle',
}
_db_engine_setting = _env('DJANGO_DB_ENGINE', 'DB_ENGINE', default='sqlite3')
DB_ENGINE = _DB_ENGINE_ALIASES.get(_db_engine_setting.lower(), _db_engine_setting)

if DB_ENGINE == 'django.db.backends.sqlite3':
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': _env('DJANGO_DB_NAME', 'DB_NAME', default=str(BASE_DIR / 'db.sqlite3')),
        }
    }
else:
    _db_name = _env('DJANGO_DB_NAME', 'DB_NAME')
    if not _db_name:
        raise ImproperlyConfigured(
            f'DJANGO_DB_NAME must be set when DJANGO_DB_ENGINE is {_db_engine_setting!r}.'
        )
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': _db_name,
            'USER': _env('DJANGO_DB_USER', 'DB_USER', default=''),
            'PASSWORD': _env('DJANGO_DB_PASSWORD', 'DB_PASSWORD', default=''),
            'HOST': _env('DJANGO_DB_HOST', 'DB_HOST', default='localhost'),
            'PORT': _env('DJANGO_DB_PORT', 'DB_PORT', default='5432'),
            'CONN_MAX_AGE': _env_int('DJANGO_DB_CONN_MAX_AGE', 'DB_CONN_MAX_AGE', default=60),
        }
    }


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# `coldstorage/static/` is picked up automatically by the staticfiles
# AppDirectoriesFinder, so it must NOT be repeated in STATICFILES_DIRS.
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []

# Media files (user uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Directories the application is allowed to read stored files from (checksums,
# file size probes, ...).  Anything outside these roots is rejected.
COLDSTORAGE_ALLOWED_STORAGE_ROOTS = [
    os.path.abspath(path)
    for path in _env_list(
        'COLDSTORAGE_ALLOWED_STORAGE_ROOTS',
        default=[str(MEDIA_ROOT)],
        separator=os.pathsep,
    )
]

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Django REST Framework configuration
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
    'DEFAULT_FILTER_BACKENDS': [
        # Required for the `filterset_fields` declared on the viewsets; without
        # it DRF ignores them silently and every filter returns everything.
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_LEVEL = _env('DJANGO_LOG_LEVEL')
_LOG_FILE = os.environ.get('DJANGO_LOG_FILE', str(BASE_DIR / 'django.log')).strip()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': _LOG_LEVEL or 'INFO',
            'propagate': True,
        },
        'coldstorage': {
            'handlers': ['console'],
            'level': _LOG_LEVEL or 'DEBUG',
            'propagate': True,
        },
    },
}

if _LOG_FILE:
    LOGGING['handlers']['file'] = {
        'level': 'INFO',
        'class': 'logging.FileHandler',
        'filename': _LOG_FILE,
    }
    for _logger in LOGGING['loggers'].values():
        _logger['handlers'].append('file')

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
# Always on, debug or not.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SESSION_COOKIE_HTTPONLY = True

# Everything below only makes sense over HTTPS, so it is tied to DEBUG rather
# than to an environment name: turning debug off is what puts the app in a
# deployed configuration.
if not DEBUG:
    # The container is intended to run behind a TLS terminating reverse proxy.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = _env_int('DJANGO_SECURE_HSTS_SECONDS', default=31536000)  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
        'DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True
    )
    SECURE_HSTS_PRELOAD = _env_bool('DJANGO_SECURE_HSTS_PRELOAD', default=True)
