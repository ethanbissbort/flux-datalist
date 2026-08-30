"""
Regression tests for the Cold Storage app.

Every test here corresponds to a defect found in the repository audit
(``AUDIT.md``). The suite exists primarily so that the class of failure that
produced those defects — a field rename that was never propagated to its call
sites, caught by nothing because there were no tests — cannot recur silently.

``test_every_registered_route_responds`` is the cheapest and broadest of these:
it walks the URLconf and asserts nothing 500s. That single test would have
caught most of the audit's findings.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import get_resolver
from rest_framework.test import APIClient

from .forms import DataItemForm
from .models import (
    Category, CostEstimate, DataItem, StorageFile, StorageProvider, Tag,
)
from .services import (
    BatchOperationService, ExportService, JSONImportService,
)


class BaseFixtureMixin:
    """Shared fixture: one category, one tagged item, one provider."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser('admin', 'a@b.c', 'pw-12345')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.category = Category.objects.create(name='Games')
        self.tag = Tag.objects.create(name='Retro')
        self.item = DataItem.objects.create(
            name='Doom', category=self.category, size_estimate_gb=2.5,
        )
        self.item.tag_set.add(self.tag)
        self.provider = StorageProvider.objects.create(
            name='S3', cost_per_gb_monthly='0.023', retrieval_cost_per_gb='0.09',
        )


class RouteSmokeTests(BaseFixtureMixin, TestCase):
    """
    The broad net: every registered route must respond without a server error.

    Audit findings 1, 4, 5, 6, 7 and 8 were all 500s or silent failures on
    routes that no test ever requested.
    """

    def setUp(self):
        super().setUp()
        # Every registered model needs at least one row, or its detail route
        # 404s and the smoke test can't tell "missing row" from "broken URL".
        StorageFile.objects.create(
            data_item=self.item, original_filename='a.bin', file_size_bytes=1,
        )
        CostEstimate.objects.create(
            data_item=self.item, provider=self.provider, estimated_size_gb=1,
        )

    def _concrete_urls(self):
        """Every URL pattern that needs no arguments, plus detail routes."""
        urls = []
        for pattern in get_resolver().url_patterns:
            urls.extend(self._walk(pattern, ''))
        return urls

    @staticmethod
    def _clean(fragment):
        """
        Strip regex anchors from one URL fragment.

        Only a leading ``^`` and a trailing ``$`` are anchors. A blanket
        replace also eats the ``^`` inside character classes, turning DRF's
        ``(?P<pk>[^/.]+)`` into ``(?P<pk>[/.]+)`` — which silently stops
        matching, so no detail route is ever discovered.
        """
        return re.sub(r'\$$', '', re.sub(r'^\^', '', str(fragment)))

    def _walk(self, pattern, prefix):
        found = []
        if hasattr(pattern, 'url_patterns'):
            for sub in pattern.url_patterns:
                found.extend(self._walk(sub, prefix + self._clean(pattern.pattern)))
            return found

        route = prefix + self._clean(pattern.pattern)
        if route.startswith('admin/'):
            return found
        # Substitute a real primary key / slug into detail routes.
        route = (
            route.replace('(?P<pk>[^/.]+)', str(self.item.pk))
                 .replace('(?P<slug>[^/.]+)', self.tag.slug)
        )
        if '(?P' in route or '<' in route:
            return found
        found.append('/' + route)
        return found

    def test_route_discovery_actually_finds_the_api(self):
        """
        Guard the guard: if URL normalization breaks, every API route 404s and
        the smoke test above passes while exercising nothing.
        """
        urls = self._concrete_urls()
        self.assertIn('/api/items/', urls)
        self.assertIn(f'/api/items/{self.item.pk}/', urls)
        self.assertIn('/api/categories/', urls)
        self.assertNotIn('', [u for u in urls if '^' in u or '$' in u])

    def test_no_discovered_route_is_missing(self):
        """A discovered GET route must not 404 — that means a malformed URL."""
        missing = [
            url for url in self._concrete_urls()
            if self.client.get(url).status_code == 404
        ]
        self.assertEqual(missing, [], f'Routes that 404: {missing}')

    def test_every_registered_route_responds(self):
        """No GET route may return 5xx."""
        failures = []
        for url in self._concrete_urls():
            try:
                response = self.client.get(url)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                failures.append(f'{url} raised {type(exc).__name__}: {exc}')
                continue
            if response.status_code >= 500:
                failures.append(f'{url} -> {response.status_code}')

        self.assertEqual(failures, [], f'Routes returning server errors: {failures}')


class TagFieldRenameRegressionTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 1: ``DataItem.tags`` was renamed to ``tags_old`` / ``tag_set``
    and nine call sites were left pointing at the removed name.
    """

    def test_list_endpoint_serializes_tags(self):
        response = self.client.get('/api/items/')
        self.assertEqual(response.status_code, 200)
        row = response.json()['results'][0]
        self.assertEqual(row['tags'], 'Retro')
        self.assertEqual(row['tags_list'], ['Retro'])
        # The dashboard reads category_name, not a nested category object.
        self.assertEqual(row['category_name'], 'Games')

    def test_search_matches_tag_names(self):
        response = self.client.get('/api/items/?search=Retro')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)

    def test_create_accepts_comma_separated_tags(self):
        response = self.client.post(
            '/api/items/',
            {'name': 'Quake', 'category': self.category.pk, 'tags': 'fps, classic'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        created = DataItem.objects.get(name='Quake')
        self.assertEqual(sorted(created.get_tags_list()), ['classic', 'fps'])

    def test_create_accepts_tag_ids(self):
        response = self.client.post(
            '/api/items/',
            {'name': 'Quake', 'category': self.category.pk, 'tag_ids': [self.tag.pk]},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(DataItem.objects.get(name='Quake').get_tags_list(), ['Retro'])

    def test_create_rejects_both_tag_inputs(self):
        response = self.client.post(
            '/api/items/',
            {
                'name': 'Quake', 'category': self.category.pk,
                'tags': 'fps', 'tag_ids': [self.tag.pk],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_update_replaces_tag_set(self):
        response = self.client.patch(
            f'/api/items/{self.item.pk}/', {'tags': 'shooter'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.item.get_tags_list(), ['shooter'])

    def test_json_import_populates_tags(self):
        payload = json.dumps([{
            'name': 'Half-Life', 'category': 'Games',
            'tags': 'fps, classic', 'size_estimate_gb': 3,
        }]).encode()

        result = JSONImportService.import_from_json(
            SimpleUploadedFile('items.json', payload)
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.imported_count, 1)
        self.assertEqual(
            sorted(DataItem.objects.get(name='Half-Life').get_tags_list()),
            ['classic', 'fps'],
        )

    def test_exports_render_tag_names(self):
        exported = json.loads(ExportService.export_to_json(DataItem.objects.all()))
        self.assertEqual(exported[0]['tags'], 'Retro')
        self.assertIn('Retro', ExportService.export_to_csv(DataItem.objects.all()))

    def test_admin_add_and_search_pages_load(self):
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get('/admin/coldstorage/dataitem/add/').status_code, 200,
        )
        self.assertEqual(
            self.client.get('/admin/coldstorage/dataitem/?q=Retro').status_code, 200,
        )


class ChecksumIntegrityTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 2: verifying a corrupted file overwrote the stored good
    checksum with the corrupted one, so re-verifying reported the file clean.
    """

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.path = os.path.join(self.media, 'artifact.bin')
        with open(self.path, 'wb') as handle:
            handle.write(b'GOOD DATA')

    def _make_file(self):
        storage_file = StorageFile.objects.create(
            data_item=self.item, original_filename='artifact.bin',
            file_size_bytes=9, storage_path=self.path, status='stored',
        )
        storage_file.calculate_checksums()
        storage_file.save()
        return storage_file

    def _corrupt(self):
        with open(self.path, 'wb') as handle:
            handle.write(b'CORRUPTED')

    def test_verification_preserves_the_baseline_checksum(self):
        with override_settings(COLDSTORAGE_ALLOWED_STORAGE_ROOTS=[self.media]):
            storage_file = self._make_file()
            good = storage_file.checksum_sha256
            self._corrupt()

            self.assertFalse(storage_file.verify_checksum())
            storage_file.refresh_from_db()

            self.assertEqual(storage_file.status, 'corrupted')
            self.assertEqual(
                storage_file.checksum_sha256, good,
                'verification must never overwrite the stored baseline digest',
            )

    def test_corruption_does_not_launder_itself_clean_on_reverify(self):
        with override_settings(COLDSTORAGE_ALLOWED_STORAGE_ROOTS=[self.media]):
            storage_file = self._make_file()
            self._corrupt()

            self.assertFalse(storage_file.verify_checksum())
            self.assertFalse(
                storage_file.verify_checksum(),
                'a second verification must still report corruption',
            )
            storage_file.refresh_from_db()
            self.assertEqual(storage_file.status, 'corrupted')

    def test_verification_without_a_baseline_is_not_a_pass(self):
        with override_settings(COLDSTORAGE_ALLOWED_STORAGE_ROOTS=[self.media]):
            storage_file = StorageFile.objects.create(
                data_item=self.item, original_filename='artifact.bin',
                file_size_bytes=9, storage_path=self.path,
            )
            self.assertFalse(storage_file.verify_checksum())

    def test_storage_path_cannot_escape_the_allowed_roots(self):
        """Audit finding 12: storage_path was an arbitrary-file-read oracle."""
        with override_settings(COLDSTORAGE_ALLOWED_STORAGE_ROOTS=[self.media]):
            escaped = StorageFile.objects.create(
                data_item=self.item, original_filename='hostname',
                file_size_bytes=1, storage_path='/etc/hostname',
            )
            with self.assertRaises(SuspiciousFileOperation):
                escaped.calculate_checksums()

    def test_traversal_out_of_an_allowed_root_is_refused(self):
        with override_settings(COLDSTORAGE_ALLOWED_STORAGE_ROOTS=[self.media]):
            escaped = StorageFile.objects.create(
                data_item=self.item, original_filename='hostname',
                file_size_bytes=1,
                storage_path=os.path.join(self.media, '..', '..', 'etc', 'hostname'),
            )
            with self.assertRaises(SuspiciousFileOperation):
                escaped.calculate_checksums()


class CategoryCycleTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 3: the API could persist a parent cycle, and the response
    serialization then span forever in get_full_path().
    """

    def setUp(self):
        super().setUp()
        self.parent = Category.objects.create(name='A')
        self.child = Category.objects.create(name='B', parent=self.parent)

    def test_api_rejects_a_cycle(self):
        response = self.client.patch(
            f'/api/categories/{self.parent.pk}/',
            {'parent': self.child.pk}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.parent.refresh_from_db()
        self.assertIsNone(self.parent.parent_id)

    def test_api_rejects_self_parenting(self):
        response = self.client.patch(
            f'/api/categories/{self.parent.pk}/',
            {'parent': self.parent.pk}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_model_clean_rejects_a_cycle(self):
        self.parent.parent = self.child
        with self.assertRaises(ValidationError):
            self.parent.clean()

    def test_traversals_terminate_on_pre_existing_corrupt_data(self):
        """A row poisoned before the guard existed must still be readable."""
        Category.objects.filter(pk=self.parent.pk).update(parent_id=self.child.pk)
        poisoned = Category.objects.get(pk=self.parent.pk)

        # Must return rather than hang; the assertion is that we get here.
        self.assertIsInstance(poisoned.get_full_path(), str)
        self.assertIsInstance(poisoned.get_descendants(), list)


class BatchOperationTests(BaseFixtureMixin, TestCase):
    """Audit finding 4: the endpoint raised TypeError on every single call."""

    def test_update_status(self):
        response = self.client.post(
            '/api/items/batch_operation/',
            {'operation': 'update_status', 'status': 'stored'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['updated'], 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'stored')

    def test_scoped_by_item_ids(self):
        other = DataItem.objects.create(name='Other', category=self.category)
        response = self.client.post(
            '/api/items/batch_operation/',
            {
                'operation': 'update_priority', 'priority': 'high',
                'item_ids': [self.item.pk],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        other.refresh_from_db()
        self.assertEqual(other.priority, 'medium')

    def test_tag_operations(self):
        extra = Tag.objects.create(name='Shooter')
        response = self.client.post(
            '/api/items/batch_operation/',
            {'operation': 'add_tags', 'tag_ids': [extra.pk]}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('Shooter', self.item.get_tags_list())

    def test_missing_parameter_is_a_client_error_not_a_500(self):
        response = self.client.post(
            '/api/items/batch_operation/',
            {'operation': 'update_status'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_operation_is_a_client_error(self):
        response = self.client.post(
            '/api/items/batch_operation/',
            {'operation': 'drop_everything'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_bulk_delete_counts_data_items_only(self):
        """Audit finding 21: the count included cascaded rows."""
        StorageFile.objects.create(
            data_item=self.item, original_filename='a', file_size_bytes=1,
        )
        CostEstimate.objects.create(
            data_item=self.item, provider=self.provider, estimated_size_gb=1,
        )

        deleted = BatchOperationService.bulk_delete(DataItem.objects.all())
        self.assertEqual(deleted, 1)


class ExportFormatTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 6: ``?format=csv`` collided with DRF's own content
    negotiation and 404'd before the view body ever ran.
    """

    def test_each_format_is_reachable(self):
        for fmt, content_type in [
            ('json', 'application/json'),
            ('csv', 'text/csv'),
            ('excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        ]:
            with self.subTest(export_format=fmt):
                response = self.client.get(f'/api/items/export/?export_format={fmt}')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], content_type)

    def test_default_is_json(self):
        response = self.client.get('/api/items/export/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_unknown_format_is_rejected(self):
        response = self.client.get('/api/items/export/?export_format=pdf')
        self.assertEqual(response.status_code, 400)

    def test_category_export_formats(self):
        for fmt in ('json', 'csv'):
            with self.subTest(export_format=fmt):
                response = self.client.get(
                    f'/api/categories/export/?export_format={fmt}'
                )
                self.assertEqual(response.status_code, 200)


class StorageFileUploadTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 7: the upload serializer omitted two non-nullable columns,
    so every upload died on a NOT NULL constraint.
    """

    def setUp(self):
        super().setUp()
        # Uploads must land in a throwaway directory. Without this the suite
        # writes real files into the project's MEDIA_ROOT on every run.
        self._media = tempfile.mkdtemp()
        overridden = override_settings(
            MEDIA_ROOT=self._media,
            COLDSTORAGE_ALLOWED_STORAGE_ROOTS=[self._media],
        )
        overridden.enable()
        self.addCleanup(overridden.disable)
        self.addCleanup(shutil.rmtree, self._media, True)

    def test_upload_populates_derived_columns_and_checksums(self):
        response = self.client.post(
            '/api/files/',
            {
                'data_item': self.item.pk,
                'file': SimpleUploadedFile('payload.bin', b'hello world'),
                'storage_location': 'local',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['file_size_bytes'], 11)
        self.assertEqual(body['original_filename'], 'payload.bin')
        self.assertEqual(body['status'], 'stored')
        # sha256 of b'hello world'
        self.assertTrue(body['checksum_sha256'].startswith('b94d27b9934d'))

    def test_upload_without_a_file_is_rejected(self):
        response = self.client.post(
            '/api/files/', {'data_item': self.item.pk}, format='multipart',
        )
        self.assertEqual(response.status_code, 400)


class WebFormTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 8: the template omitted required fields so the form could
    never validate, and finding 18: it wrote to the deprecated tags column.
    """

    def _payload(self, **overrides):
        payload = {
            'name': 'Quake',
            'category': self.category.pk,
            'subcategory': '',
            'description': 'd',
            'examples': '',
            'size_estimate_gb': '2',
            'source_url': '',
            'notes': '',
            'priority': 'medium',
            'status': 'planned',
            'tags': 'fps, classic',
        }
        payload.update(overrides)
        return payload

    def test_form_validates_with_the_rendered_fields(self):
        form = DataItemForm(data=self._payload())
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_writes_tags_to_the_relation_not_the_legacy_column(self):
        form = DataItemForm(data=self._payload())
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()

        self.assertEqual(sorted(item.get_tags_list()), ['classic', 'fps'])
        self.assertEqual(
            item.tags_old, '',
            'the web form must not write to the deprecated tags_old column',
        )

    def test_form_prepopulates_tags_when_editing(self):
        form = DataItemForm(instance=self.item)
        self.assertEqual(form.fields['tags'].initial, 'Retro')

    def test_index_page_renders_every_required_field(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for field in ('name', 'category', 'priority', 'status'):
            with self.subTest(field=field):
                self.assertIn(f'name="{field}"', body)

    def test_authenticated_post_creates_an_item(self):
        self.client.force_login(self.user)
        response = self.client.post('/', self._payload())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DataItem.objects.filter(name='Quake').exists())

    def test_dashboard_renders(self):
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)


class AuthorizationTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 9: the web views accepted writes from anonymous visitors
    while the API correctly refused them.
    """

    def test_anonymous_cannot_create_via_the_web_form(self):
        anon = APIClient()
        response = anon.post('/', {
            'name': 'Anon', 'category': self.category.pk,
            'priority': 'medium', 'status': 'planned',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DataItem.objects.filter(name='Anon').exists())

    def test_anonymous_cannot_bulk_import(self):
        anon = APIClient()
        payload = json.dumps([{'name': 'X', 'category': 'Y'}]).encode()
        response = anon.post(
            '/import-json/',
            {'json_file': SimpleUploadedFile('x.json', payload)},
            format='multipart',
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DataItem.objects.filter(name='X').exists())

    def test_login_redirect_target_actually_exists(self):
        """
        The write guard redirects to LOGIN_URL. If that route is missing the
        redirect lands on a 404 and the queued message is discarded with it.
        """
        anon = APIClient()
        response = anon.post('/', {
            'name': 'Anon', 'category': self.category.pk,
            'priority': 'medium', 'status': 'planned',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign in')

    def test_anonymous_cannot_write_via_the_api(self):
        anon = APIClient()
        response = anon.post(
            '/api/items/', {'name': 'Anon', 'category': self.category.pk},
            format='json',
        )
        self.assertIn(response.status_code, (401, 403))

    def test_anonymous_can_still_read(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/items/').status_code, 200)


class FilterBackendTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 11: every ``filterset_fields`` declaration was ignored
    because django-filter was not installed, so filters returned everything.
    """

    def setUp(self):
        super().setUp()
        self.other_category = Category.objects.create(name='Software')
        DataItem.objects.create(name='Emacs', category=self.other_category)

    def test_category_filter_actually_filters(self):
        response = self.client.get(f'/api/items/?category={self.category.pk}')
        self.assertEqual(response.status_code, 200)
        names = [row['name'] for row in response.json()['results']]
        self.assertEqual(names, ['Doom'])

    def test_status_filter_actually_filters(self):
        self.item.status = 'stored'
        self.item.save()
        response = self.client.get('/api/items/?status=stored')
        self.assertEqual(response.json()['count'], 1)


class CostEstimateTests(BaseFixtureMixin, TestCase):
    """Audit finding 19: save() silently discarded manual cost overrides."""

    def test_costs_are_calculated_when_not_supplied(self):
        estimate = CostEstimate.objects.create(
            data_item=self.item, provider=self.provider, estimated_size_gb=100,
        )
        self.assertEqual(float(estimate.monthly_storage_cost), 2.30)

    def test_explicit_costs_are_preserved(self):
        estimate = CostEstimate.objects.create(
            data_item=self.item, provider=self.provider,
            estimated_size_gb=100, monthly_storage_cost='9.99',
        )
        self.assertEqual(float(estimate.monthly_storage_cost), 9.99)

    def test_manual_override_survives_a_later_save(self):
        estimate = CostEstimate.objects.create(
            data_item=self.item, provider=self.provider, estimated_size_gb=100,
        )
        estimate.monthly_storage_cost = '0.00'
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(
            float(estimate.monthly_storage_cost), 0.00,
            'a deliberate zero must not be treated as "unset" and recalculated',
        )

    def test_explicit_recalculation_still_works(self):
        estimate = CostEstimate.objects.create(
            data_item=self.item, provider=self.provider,
            estimated_size_gb=100, monthly_storage_cost='9.99',
        )
        estimate.calculate_costs()
        estimate.save()
        self.assertEqual(float(estimate.monthly_storage_cost), 2.30)


class QueryCountTests(BaseFixtureMixin, TestCase):
    """
    Audit finding 16: the list serializers issued a COUNT per row (78 queries
    for 26 categories, 26 for 25 tags). These bounds are deliberately loose —
    they catch a reintroduced N+1, not a one-query regression.
    """

    def setUp(self):
        super().setUp()
        for i in range(25):
            item = DataItem.objects.create(name=f'item{i}', category=self.category)
            item.tag_set.add(Tag.objects.create(name=f'tag{i}'))
            Category.objects.create(name=f'child{i}', parent=self.category)

    def test_category_list_does_not_scale_with_row_count(self):
        with self.assertNumQueries(2):  # count + page
            self.client.get('/api/categories/')

    def test_tag_list_does_not_scale_with_row_count(self):
        with self.assertNumQueries(2):
            self.client.get('/api/tags/')

    def test_item_list_does_not_scale_with_row_count(self):
        with self.assertNumQueries(3):  # count + page + tag prefetch
            self.client.get('/api/items/')


class SettingsPostureTests(TestCase):
    """
    Audit finding 13: a hardcoded, published SECRET_KEY plus DEBUG defaulting
    on meant one forgotten environment variable produced a debug server signing
    sessions with a key anyone could read out of the repository.
    """

    def test_no_published_secret_key_in_the_settings_module(self):
        source = (
            Path(__file__).resolve().parent.parent
            / 'coldstorage_project' / 'settings.py'
        ).read_text()
        self.assertNotIn(
            'django-insecure', source,
            'settings.py must not carry a checked-in secret key; the '
            'development fallback is generated per checkout',
        )

    def test_debug_off_without_a_key_refuses_to_start(self):
        script = (
            "import os, sys; sys.path.insert(0, %r);"
            "os.environ['DJANGO_SETTINGS_MODULE'] = 'coldstorage_project.settings';"
            "os.environ['DJANGO_DEBUG'] = '0';"
            "os.environ.pop('DJANGO_SECRET_KEY', None);"
            "import django; django.setup()"
        ) % str(Path(__file__).resolve().parent.parent)

        env = {k: v for k, v in os.environ.items() if k != 'DJANGO_SECRET_KEY'}
        env['DJANGO_DEBUG'] = '0'
        result = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', result.stderr)

    def test_security_flags_are_on_when_debug_is_off(self):
        script = (
            "import os, sys; sys.path.insert(0, %r);"
            "os.environ['DJANGO_SETTINGS_MODULE'] = 'coldstorage_project.settings';"
            "import django; django.setup();"
            "from django.conf import settings as s;"
            "print(s.DEBUG, s.SECURE_SSL_REDIRECT, s.SESSION_COOKIE_SECURE,"
            " s.CSRF_COOKIE_SECURE, s.SECURE_HSTS_SECONDS > 0)"
        ) % str(Path(__file__).resolve().parent.parent)

        env = dict(os.environ)
        env['DJANGO_DEBUG'] = '0'
        env['DJANGO_SECRET_KEY'] = secrets.token_urlsafe(64)
        result = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ['False', 'True', 'True', 'True', 'True'])
