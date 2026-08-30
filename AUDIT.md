# Repository Audit — flux-datalist (Cold Storage)

**Date:** 2026-08-30
**Commit audited:** `bb3b0f7`
**Scope:** Full repository — models, API, web views, admin, templates, services, settings, packaging, docs, repo hygiene.

## Method

Findings were **verified by execution**, not by reading alone. Django 5.2.17 + DRF 3.18 were
installed against `requirements.txt`, migrations were applied to a throwaway SQLite database, and
every URL in `coldstorage/urls.py` plus the admin and service layer were exercised with the Django
test client. Each finding below records the observed failure. Two items are marked *by inspection*
where the environment could not run them (no Docker daemon); they are called out explicitly.

---

## Executive summary

The project does not work. **12 of 25 exercised entry points return HTTP 500 or silently fail**,
including the primary list API, item creation, all exports, JSON import, the dashboard page, the
web "Add item" form, and the admin add/edit page for the core model.

Nearly all of it traces to **one unfinished refactor**. Commit `f4cfb2d` renamed
`DataItem.tags` to `tags_old` and added a `tag_set` M2M, but nine call sites across five files were
never updated. There are no tests and no CI, so nothing caught it.

Two findings are worse than "broken" — they are silently wrong, which for an archival tool is the
dangerous category:

- **`verify_checksum()` destroys the evidence of corruption it just found** (Finding 2). Detecting
  bit-rot overwrites the known-good checksum with the corrupted file's checksum. Re-verify then
  reports the file **clean**. This defeats the app's core purpose.
- **A category cycle permanently hangs a worker** (Finding 3), and poisons the row so every
  later read of it hangs too.

### Status of every exercised entry point

| Entry point | Result |
|---|---|
| `GET /api/items/` | **500** `ImproperlyConfigured` |
| `POST /api/items/` | **500** `ImproperlyConfigured` |
| `GET /api/items/?search=` | **500** `FieldError` |
| `GET /api/items/export/?format=json` | **500** `AttributeError` |
| `GET /api/items/export/?format=csv` \| `excel` | **404** (unreachable, see Finding 6) |
| `POST /api/items/batch_operation/` | **500** `TypeError` |
| `POST /api/files/` (upload) | **500** `IntegrityError` |
| `PATCH /api/categories/{id}/` (cycle) | **hangs forever** |
| `GET /dashboard/` | **500** `TemplateSyntaxError` |
| `POST /` (add item via web form) | silently rejected, always |
| JSON import | imports **0** rows, every entry errors |
| Admin → DataItem → add/edit | **500** `FieldError` |
| Admin → DataItem → search | **500** `FieldError` |
| `GET /api/items/{id}/`, `/statistics/`, `/api/categories/`, `/api/tags/`, `/api/providers/`, `/api/files/`, `/api/costs/`, `GET /` | OK |

---

## Critical

### 1. An unfinished rename left nine dead references to `DataItem.tags`

`DataItem.tags` no longer exists — `models.py` defines `tag_set` (M2M) and `tags_old` (deprecated
CharField). Nine call sites still reference the removed name. Each one is a hard failure at runtime,
not a warning.

| # | Location | Breaks | Observed |
|---|---|---|---|
| 1 | `coldstorage/serializers.py:56` | `GET /api/items/` | `ImproperlyConfigured: Field name 'tags' is not valid for model 'DataItem'` |
| 2 | `coldstorage/serializers.py:83` | `POST`/`PUT`/`PATCH /api/items/` | same |
| 3 | `coldstorage/views.py:93` | `?search=` on items | `FieldError: Cannot resolve keyword 'tags' into field` |
| 4 | `coldstorage/services.py:249` | all three export formats | `AttributeError: 'DataItem' object has no attribute 'tags'` |
| 5 | `coldstorage/services.py:281` | CSV export columns | (same path) |
| 6 | `coldstorage/services.py:344` | Excel export columns | (same path) |
| 7 | `coldstorage/services.py:111` | JSON import | `TypeError: DataItem() got unexpected keyword arguments: 'tags'` — **every** entry fails |
| 8 | `coldstorage/services.py:179` | `DataItemService.create_from_form_data` | same `TypeError` |
| 9 | `coldstorage/admin.py:60`, `admin.py:69` | admin search; admin add/edit page | `FieldError: Unknown field(s) (tags) specified for DataItem` |

The JSON import failure is the quietest and the worst: `import_from_json` catches the exception
per-entry and appends it to an error list, so a 500-row import reports "0 imported, 500 errors"
rather than crashing. Verified:

```
JSONImportService.import_from_json -> imported=0
  errors=["Entry 1: DataItem() got unexpected keyword arguments: 'tags'"]
```

**Note:** `DataItemWithTagsSerializer` (`serializers.py:271`) is already written correctly — it maps
`tags` → `tag_set` and handles `tag_ids` on write. It is imported in `views.py:22` and then **never
used by any viewset**. The fix for items 1 and 2 is already in the tree, just unwired.

**Recommended fix:** wire `DataItemWithTagsSerializer` into `DataItemViewSet.get_serializer_class()`;
replace `'tags'` with `'tags_old'` or a `get_tags_display()` accessor in the export/admin paths;
change `tags=` to a post-create `item.add_tags_from_string(...)` in the two `objects.create()` calls
(that helper already exists at `models.py:296`).

### 2. `verify_checksum()` overwrites the known-good checksum with the corrupted one

`models.py:497`. The method stores the originals in local variables, calls `calculate_checksums()`
(which mutates `self.checksum_md5` / `self.checksum_sha256` in place), compares, sets
`status='corrupted'` — and then calls `self.save()`, persisting the **new, corrupted** checksums over
the originals. The baseline needed to ever detect this corruption again is gone.

Verified against a file mutated on disk between writes:

```
stored sha256 (good): f98b74525b355120   status: stored
verify #1 -> False    status: corrupted
sha256 in DB now:     a7f0f1d4185f5309   changed from good?: True
verify #2 -> True     status: verified    <-- corruption now reports CLEAN
```

A single re-verification — or the admin's "Verify file checksums" bulk action run twice
(`admin.py:247`) — silently launders a corrupted archive back to `verified`. For a cold-storage
integrity tool this is the most damaging bug in the repository.

**Recommended fix:** compute into locals and never write recalculated digests back to the stored
columns. Persist only `status`, `last_verified_at`, and `verification_error`; expose the recomputed
digest in the response for diagnostics if useful.

### 3. Category cycles are unguarded — one request hangs a worker permanently

`Category.get_full_path()` (`models.py:36`) walks `parent` in an unbounded `while` loop;
`get_descendants()` (`models.py:45`) recurses with no cycle guard. `CategoryForm.clean()` checks for
cycles, but **the REST API never uses that form** — `CategorySerializer` has no such validation, and
the model has no constraint.

Verified: `PATCH /api/categories/{A}/ {"parent": B}` where B is A's own child.

```
PATCH A.parent=B (B is A's own child) -> REQUEST NEVER RETURNS (hung >5s, 100% CPU)
cycle persisted in DB: True
get_full_path(): INFINITE LOOP
```

The write commits *before* the response is serialized, so the cycle is persisted and then
`full_path` (a `CategorySerializer` field) spins forever. The row is permanently poisoned: every
later `GET` touching it, plus every CSV/JSON category export, hangs the same way. Any authenticated
user can take down a worker per request, and the damage survives a restart.

**Recommended fix:** move the cycle check into `Category.clean()` / a serializer `validate_parent()`
so both paths enforce it, and add a depth cap to both traversal methods as a backstop.

---

## High

### 4. `batch_operation` fails on every call

`views.py:165` calls `BatchOperationService.get_batch_operation_summary(operation, queryset, **request.data)`.
`request.data` still contains the `operation` key, which is also passed positionally →
`TypeError: got multiple values for argument 'operation'`. Caught by the bare `except Exception` two
lines down and returned as a **500**. Verified: `POST /api/items/batch_operation/ -> 500`.

Secondary: missing parameters raise `KeyError` (e.g. `kwargs['status']`), which is not a `ValueError`,
so bad client input also returns 500 instead of 400.

**Recommended fix:** pop `operation` and `item_ids` out of the kwargs before forwarding, and catch
`KeyError` alongside `ValueError` for the 400 path.

### 5. `/dashboard/` returns 500, and has four further defects behind it

The immediate failure is `TemplateSyntaxError: Could not parse the remainder: '()' from 'tag.trim()'`
at `templates/dashboard.html:71`. Django parses `{{ … }}` server-side before Vue ever sees it, and
Django's template language has no call syntax.

Fixing that one line still leaves the page non-functional:

- **Every Vue interpolation is consumed by Django.** `{{ item.name }}`, `{{ cat }}`, `{{ name }}`
  resolve against the Django context, find nothing, and render as empty strings. Vue receives a
  template with the data bindings already stripped out.
- **`fetch('/api/items/')` expects an array**, but `PAGE_SIZE: 100` is set in
  `REST_FRAMEWORK`, so the response is `{count, next, previous, results}`. `data.map(...)` throws
  `TypeError`. (Moot today — that endpoint 500s per Finding 1.)
- **`i.category.name`** (`dashboard.html:153`) — the list serializer returns `category` as an
  integer PK, not an object.
- **`toggleTagFilter`** is bound at `dashboard.html:70` but never defined; the only method in the
  component is `drawChart`.

Separately, the view builds a rich context (`status_breakdown`, `priority_breakdown`,
`category_stats`) that the template never references — all of it is dead.

**Recommended fix:** set Vue's `delimiters: ['[[', ']]']`, or wrap the markup in `{% verbatim %}`;
read `data.results`; expose `category_name` instead of the PK; define or remove `toggleTagFilter`.

### 6. CSV and Excel export are unreachable — `?format=` collides with DRF

`ExportService.export_to_csv` / `export_to_excel` are complete and correct, but no client can reach
them. DRF's `URL_FORMAT_OVERRIDE` is `'format'`, so `?format=csv` is intercepted by content
negotiation *before the view body runs*. With only `JSONRenderer` and `BrowsableAPIRenderer`
configured, DRF raises `Http404`. Verified:

```
GET /api/items/export/?format=csv   -> 404
GET /api/items/export/?format=excel -> 404
GET /api/items/export/?format=json  -> 500 (Finding 1)
```

So exports are 100% unreachable: two formats 404, the third 500s.

**Recommended fix:** rename the query parameter (e.g. `?export_format=csv`), or use distinct
routes (`/export/csv/`), or register real renderer classes.

### 7. File upload returns 500 — required columns are never populated

`StorageFileUploadSerializer` (`serializers.py:162`) exposes only `data_item`, `file`,
`storage_location`, `notes`. But `original_filename` and `file_size_bytes` are non-nullable model
fields with no default. Verified:

```
POST /api/files/ -> 500 IntegrityError:
  NOT NULL constraint failed: coldstorage_storagefile.file_size_bytes
```

Compounding this, the logic that *would* fill those fields and compute checksums lives in
`StorageFileSerializer.create()` — but `get_serializer_class()` returns the **upload** serializer for
the `create` action, so that method is dead code on the only path that calls it.

**Recommended fix:** move the `create()` override onto `StorageFileUploadSerializer` and set
`original_filename` / `file_size_bytes` from the uploaded file before the insert.

### 8. The web "Add item" form can never be submitted

`templates/index.html` hand-rolls its inputs instead of rendering the bound `DataItemForm`. It omits
`priority` and `status`, which are required (`blank=False`), and posts a `tags` field the form does
not accept (the form uses `tags_old`). Verified with exactly the fields the template posts:

```
DataItemForm valid: False
errors: {'priority': ['This field is required.'], 'status': ['This field is required.']}
```

The failure is invisible: `index.html` has no `{% for message in messages %}` block, so the
`messages.error(...)` calls in the view render nowhere. The user submits, the page reloads, nothing
happens, no explanation. `filter_form` is passed to the template and never rendered either.

**Recommended fix:** render `{{ form }}` (the widgets and CSS classes are already defined in
`forms.py`) and add a messages block.

### 9. Unauthenticated writes on the web views

DRF is configured with `IsAuthenticatedOrReadOnly`, but the function views bypass DRF entirely and
have no `@login_required`. Verified with an anonymous client:

```
POST / as anonymous -> 302   item created: True
```

`POST /import-json/` is likewise open — an anonymous visitor can bulk-load arbitrary records and
auto-create categories (`get_or_create_category`). The API is locked down; the front door is not.

**Recommended fix:** add `@login_required` to `index` and `import_json`, matching the API's posture.

### 10. Production mode cannot start — `psycopg2` is not a dependency

`settings.py:169-181` switches `DATABASES` to `django.db.backends.postgresql` when
`DJANGO_ENV=production`, but neither `psycopg2` nor `psycopg` appears in `requirements.txt`.
Verified — the production profile dies at import:

```
django.core.exceptions.ImproperlyConfigured: Error loading psycopg2 or psycopg module
```

**Recommended fix:** add `psycopg[binary]>=3.1` to `requirements.txt`.

---

## Medium

### 11. Every `filterset_fields` declaration is silently ignored

All six viewsets declare `filterset_fields`, but `django-filter` is **not installed and not in
`requirements.txt`**, and `DEFAULT_FILTER_BACKENDS` contains only `SearchFilter` and `OrderingFilter`.
DRF ignores the attribute without any warning. `?category=…`, `?status=…`, `?is_active=…` are all
no-ops that return the unfiltered list — a filter that silently returns everything is worse than one
that errors. `PRIORITY_2_IMPLEMENTATION.md` documents these filters as working.

**Recommended fix:** add `django-filter` and `DjangoFilterBackend`, or delete the attributes.

### 12. Arbitrary server-side file read via `storage_path`

`calculate_checksums()` (`models.py:470`) opens `self.storage_path` directly. That field is writable
through the API and admin with no allow-list or path validation. Verified:

```
StorageFile(storage_path='/etc/hostname').calculate_checksums()
  -> md5 6520213d3695a344f306efffa2523807
```

This requires an authenticated user, so it is privilege escalation rather than pre-auth RCE — but it
turns any account into a filesystem oracle: confirm existence of any path the worker can read, and
fingerprint contents by digest (effective against small or guessable files, e.g. confirming a
credential file's exact contents from a candidate list).

**Recommended fix:** confine `storage_path` to a configured root via `os.path.realpath` + prefix
check before opening.

### 13. Production security settings are unset

`manage.py check --deploy` against the production profile (with a valid 64-byte key, so this is not a
test artifact):

- `security.W004` — `SECURE_HSTS_SECONDS` unset
- `security.W008` — `SECURE_SSL_REDIRECT` not `True`
- `security.W012` — `SESSION_COOKIE_SECURE` not `True`
- `security.W016` — `CSRF_COOKIE_SECURE` not `True`

Related settings issues:

- `SECRET_KEY` is hardcoded at `settings.py:12` and only replaced inside the `DJANGO_ENV=production`
  branch. Any deployment that forgets that one variable runs with a published key **and**
  `DEBUG=True`, which together expose full tracebacks and session forgery.
- `SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')` returns `None` if unset rather than failing loudly.
- `docker-compose.yml` sets `DEBUG=True`, which `settings.py` never reads. The variable does nothing;
  `DEBUG` is `True` regardless.
- `SECURE_BROWSER_XSS_FILTER` is a no-op in all current browsers.

**Recommended fix:** fail fast on a missing key, default `DEBUG` to `False` and opt *in* to it, and
set the four cookie/transport flags in the production branch.

### 14. No tests, no CI

No test files, no `.github/workflows`, no `tox.ini`/`pytest.ini`/`Makefile`. This is the direct cause
of Finding 1 — nine broken call sites across two feature commits, none caught. `manage.py check`
passes clean, which makes the repo look healthier than it is; the failures only surface on request.

**Correction to an earlier draft of this finding:** it claimed `ALLOWED_HOSTS` omits `testserver`
and that the first test written would therefore get `400 DisallowedHost`. That is wrong — Django's
`setup_test_environment()` appends `testserver` automatically, so `manage.py test` is unaffected.
The 400s seen while auditing came from driving the test client *outside* the test runner, which is
an artifact of the audit harness, not a defect in the project.

**Recommended fix:** a smoke test that GETs every registered route and asserts it does not 5xx.
That single test catches most of the findings here.

### 15. Docker build is broken *(by inspection — no Docker daemon available in this environment)*

`Dockerfile` sets `WORKDIR /app` and runs `python manage.py migrate`, but `COPY . /app/` places
`manage.py` at `/app/coldstorage_project/manage.py`. There is no `/app/manage.py`, so the `RUN` fails
and the build never completes. `CMD` has the same wrong path. The README's only quick-start
instruction is `docker-compose up --build`, so the documented setup path cannot work.

Further issues in the same two files:

- `RUN python manage.py migrate` at **build** time bakes a SQLite DB into the image.
- `docker-compose.yml` bind-mounts `.:/app`, shadowing the image contents anyway.
- `runserver` is Django's development server and is not suitable as a production `CMD`.
- Container runs as root; no non-root user.
- `version: "3.9"` is obsolete under Compose v2.
- README quick-start clones a placeholder URL (`https://github.com/your-repo/coldstorage.git`).

**Recommended fix:** `WORKDIR /app/coldstorage_project`, drop the build-time `migrate` (run it at
container start), and switch to gunicorn with a non-root user.

### 16. N+1 queries in the list serializers

Measured at the serializer level:

| Serializer | Rows | Queries |
|---|---|---|
| `CategorySerializer` | 26 | **78** (3N — `children_count` + `item_count` per row) |
| `TagSerializer` | 25 | **26** (N+1 — `get_usage_count()` per row) |

`StorageProviderSerializer.get_estimate_count` and `CostEstimate`'s `SerializerMethodField`s have the
same shape.

**Recommended fix:** annotate with `Count(...)` in each viewset's `get_queryset()` and read the
annotation in the serializer.

### 17. `generate_django_files.py` will clobber 13 tracked files

The script writes hardcoded, stale copies of files that have since been refactored. Running it
silently overwrites **13 tracked files**, including `requirements.txt`, `Dockerfile`,
`docker-compose.yml`, `setup_project.py`, and all four URL/config modules. It also recreates
`coldstorage/urls.py`, which commit `fddce30` deliberately deleted as outdated.

It served its purpose at scaffolding time and is now a loaded footgun sitting in the repo root.

**Recommended fix:** delete it; the files it generates are tracked in git.

---

## Low

| # | Finding | Location |
|---|---|---|
| 18 | Two tag stores diverge — the web form writes `tags_old` (`forms.py:17`), the API is meant to write `tag_set`. The "deprecated" field is the only one the UI touches. | `forms.py`, `models.py` |
| 19 | `CostEstimate.save()` recalculates whenever `monthly_storage_cost` is falsy — so a legitimately free tier (local/NAS at $0.00) recomputes on every save, and manual cost overrides are silently discarded. | `models.py:643` |
| 20 | `TagAdmin.usage_count_display.admin_order_field = 'data_items__count'` references an annotation that is never applied; sorting that column errors. | `admin.py:337` |
| 21 | `bulk_delete` returns `queryset.delete()`'s total, which counts cascaded `StorageFile`/`CostEstimate` rows — so the API reports more items deleted than existed. | `services.py:487` |
| 22 | JSON import has no transaction; a mid-file failure leaves a partial import plus orphaned auto-created categories. | `services.py:140` |
| 23 | Migration `0002` can raise `IntegrityError` when two tag names slugify identically (`"Sci-Fi"` / `"Sci Fi"`) — it catches `Tag.DoesNotExist` on slug but `name` is also unique. | `migrations/0002:33-37` |
| 24 | Bare `except:` swallows everything in the Excel column-width loop. | `services.py:362` |
| 25 | CDN assets loaded with no SRI and unpinned tags (`vue@3`, `chart.js` with no version). | `index.html:6`, `dashboard.html:6-8` |
| 26 | Dependencies unpinned (`Django>=4.2` resolves to 5.2.17 today; migrations were generated on 5.2.8). No lockfile. | `requirements.txt` |
| 27 | `staticfiles.W004` — `STATICFILES_DIRS` points at `coldstorage/static`, which does not exist. The only warning `manage.py check` currently emits. | `settings.py:97` |
| 28 | Two seed JSON files live under `MEDIA_ROOT` and are committed; `MEDIA_ROOT` is served publicly in `DEBUG`. Seed data belongs in `fixtures/`. | `coldstorage_project/media/` |
| 29 | `except Exception` blocks in the viewsets return raw `str(e)` to clients, leaking internal paths and schema details. | `views.py:172`, `views.py:207`, `views.py:222` |
| 30 | Docs overstate status: 36 completeness markers (✅ / "COMPLETE" / "Production Ready") across `FEATURE_ROADMAP.md`, `PRIORITY_1_IMPLEMENTATION.md`, `PRIORITY_2_IMPLEMENTATION.md` for features that return 500. `PRIORITY_2` includes a "🧪 Testing Checklist" that was evidently never run. | docs |

**Clean:** no secrets committed (history scanned), `.gitignore` correctly covers `db.sqlite3`,
`*.log`, and `.env`, no build artifacts or `__pycache__` tracked, MIT `LICENSE` present.

---

## Suggested order of work

1. **Finding 2** (checksum destruction) — silent data-integrity loss; nothing else matters if the
   archive can't be trusted.
2. **Finding 1** (the `tags` rename) — one coherent change unblocks 8 of the 12 broken endpoints.
3. **Finding 3** (category cycle) — trivially reachable, permanent worker hang.
4. **Finding 14** (a route smoke test) — before any further features; it would have caught 1, 4, 5,
   6, 7, 8 and would guard the fixes above.
5. Findings 9, 12, 13 (auth and settings) — before this is exposed to any network.
6. Findings 4–8, 10, 11, 15 — remaining broken surfaces.
7. Findings 16–30 — quality, performance, hygiene.

Finding 1 alone is roughly a one-file-per-site change with `DataItemWithTagsSerializer` already
written; the critical tier is well under a day's work. The larger risk is that the documentation
currently asserts all of this is complete, so nobody is looking.
