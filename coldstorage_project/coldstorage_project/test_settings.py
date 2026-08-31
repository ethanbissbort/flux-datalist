"""
Settings for running the test suite against the *production* security profile.

The default settings turn the deployed configuration on when ``DEBUG`` is off:
HTTPS redirect, HSTS, and secure session and CSRF cookies. Running the suite
that way with no adjustment does not work — ``SECURE_SSL_REDIRECT`` answers
every test-client request with a 301 before it reaches a view, so most of the
suite fails with a misleading status rather than a real one.

The tempting workaround is to test with ``DEBUG=1``, which is what CI did
originally. That leaves the suite exercising a configuration nobody deploys:
the middleware stack, cookie flags and security headers under test are not the
ones that will serve real traffic.

This module closes that gap. It imports the real settings with debug **off**,
so the production posture is genuinely active, and then relaxes exactly one
setting — the HTTPS redirect — because the Django test client speaks plain
HTTP and cannot follow it meaningfully.

Nothing else is overridden. ``SecuritySettingsUnderTestTests`` in
``coldstorage/tests.py`` asserts that, so this file cannot quietly drift back
into being a second development configuration.

Usage::

    python manage.py test coldstorage --settings=coldstorage_project.test_settings
"""
import os
import secrets

# The parent module reads both of these at import time, so they have to be in
# place before it is imported.
#
# DEBUG is forced rather than defaulted: this module exists specifically to
# exercise the debug-off configuration, so an inherited DJANGO_DEBUG=1 from a
# developer's shell must not silently turn it back into a development run.
os.environ['DJANGO_DEBUG'] = '0'

# Debug-off settings refuse to start without a key. Generate a throwaway one
# rather than committing a constant — a checked-in key is the exact hazard the
# audit flagged, and tests have no need for one that is stable across runs.
os.environ.setdefault('DJANGO_SECRET_KEY', secrets.token_urlsafe(64))

from .settings import *  # noqa: E402,F403

# The single relaxation, and the reason this module exists.
#
# django.test.Client issues plain-HTTP requests against 'testserver'. With the
# redirect on, SecurityMiddleware returns 301 to the https:// URL before any
# view runs, so assertions see a redirect instead of the real response. There
# is no way for the test client to follow it to a real TLS listener, and
# faking one via SECURE_PROXY_SSL_HEADER would mean testing a request the
# middleware never actually inspects.
#
# Everything else the production profile turns on stays on, including
# SESSION_COOKIE_SECURE and CSRF_COOKIE_SECURE — the test client sets cookies
# directly rather than honouring the Secure attribute, so those remain
# faithful to production without breaking anything.
SECURE_SSL_REDIRECT = False
