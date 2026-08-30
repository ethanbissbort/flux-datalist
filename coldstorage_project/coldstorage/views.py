"""
Views for the Cold Storage app.
Handles both REST API endpoints and traditional template-based views.
"""
import logging

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Sum, Avg, Q
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_http_methods

from .models import (
    DataItem, Category, StorageFile, Tag,
    StorageProvider, CostEstimate
)
from .serializers import (
    CategorySerializer, DataItemSerializer,
    DataItemListSerializer, DataItemWriteSerializer,
    StorageFileSerializer, StorageFileUploadSerializer, TagSerializer,
    StorageProviderSerializer, CostEstimateSerializer
)
from .forms import DataItemForm, JSONImportForm, DataItemFilterForm
from .services import (
    JSONImportService, DataItemService, ExportService, BatchOperationService
)

logger = logging.getLogger(__name__)

#: Export formats understood by the ``export`` actions. The query parameter is
#: deliberately NOT called ``format``: DRF reserves that name
#: (``URL_FORMAT_OVERRIDE``) for content negotiation and raises 404 for any
#: value that has no matching renderer, before the view body ever runs.
EXPORT_FORMAT_PARAM = 'export_format'


def _export_format(request: HttpRequest) -> str:
    """Read the requested export format, defaulting to JSON."""
    return (request.query_params.get(EXPORT_FORMAT_PARAM) or 'json').lower()


class CategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Category model.
    Provides CRUD operations via REST API.
    """
    serializer_class = CategorySerializer
    filterset_fields = ['parent']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        """
        Annotate the counts the serializer reports, so a list of N categories
        costs one query instead of 2N+1.

        ``full_path`` walks the ancestor chain, so pull the first two levels of
        parents along too. Deeper hierarchies still cost a query per extra
        level — inherent to an adjacency list without a recursive CTE — but
        two levels covers the shapes this data actually has.
        """
        return Category.objects.select_related('parent', 'parent__parent').annotate(
            children_count_annotated=Count('children', distinct=True),
            item_count_annotated=Count('data_items', distinct=True),
        )

    @action(detail=True, methods=['get'])
    def items(self, request: HttpRequest, pk: int = None) -> Response:
        """Get all items in this category."""
        category = self.get_object()
        items = category.data_items.all()
        serializer = DataItemListSerializer(items, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def statistics(self, request: HttpRequest, pk: int = None) -> Response:
        """Get statistics for this category."""
        category = self.get_object()

        stats = {
            'item_count': category.data_items.count(),
            'total_size_gb': category.data_items.aggregate(
                total=Sum('size_estimate_gb')
            )['total'] or 0,
            'children_count': category.children.count(),
        }
        return Response(stats)

    @action(detail=False, methods=['get'])
    def export(self, request: HttpRequest) -> HttpResponse:
        """
        Export categories as CSV or JSON.

        Selected with ``?export_format=csv|json`` — see EXPORT_FORMAT_PARAM for
        why this is not ``?format=``.
        """
        format_type = _export_format(request)
        queryset = self.filter_queryset(self.get_queryset())

        if format_type == 'csv':
            content = ExportService.export_categories_to_csv(queryset)
            response = HttpResponse(content, content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="categories.csv"'
            return response
        if format_type == 'json':
            content = ExportService.export_categories_to_json(queryset)
            response = HttpResponse(content, content_type='application/json')
            response['Content-Disposition'] = 'attachment; filename="categories.json"'
            return response

        return Response(
            {'error': f"Unsupported export format '{format_type}'. Use csv or json."},
            status=400,
        )


class DataItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for DataItem model.
    Provides CRUD operations via REST API with different serializers for read/write.
    """
    filterset_fields = ['category', 'status', 'priority']
    # 'tags' is not a field on DataItem — tag names live on the related Tag
    # rows, and the legacy free-text column is 'tags_old'.
    search_fields = [
        'name', 'description', 'subcategory', 'tag_set__name', 'tags_old',
    ]
    ordering_fields = ['name', 'created_at', 'updated_at', 'size_estimate_gb']
    ordering = ['-updated_at']

    def get_queryset(self):
        """Prefetch tags — every representation renders them."""
        return (
            DataItem.objects
            .select_related('category', 'category__parent')
            .prefetch_related('tag_set')
        )

    def get_serializer_class(self):
        """Use different serializers for list, detail, and write operations."""
        if self.action == 'list':
            return DataItemListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return DataItemWriteSerializer
        return DataItemSerializer

    @action(detail=False, methods=['get'])
    def statistics(self, request: HttpRequest) -> Response:
        """Get overall statistics about data items."""
        stats = DataItemService.get_statistics()
        return Response(stats)

    @action(detail=False, methods=['get'])
    def by_category(self, request: HttpRequest) -> Response:
        """Get items grouped by category with statistics."""
        category_stats = DataItemService.get_category_statistics()
        return Response(category_stats)

    @action(detail=False, methods=['get'])
    def export(self, request: HttpRequest) -> HttpResponse:
        """
        Export data items as CSV, JSON or Excel.

        Selected with ``?export_format=csv|json|excel`` — see
        EXPORT_FORMAT_PARAM for why this is not ``?format=``.
        """
        format_type = _export_format(request)
        queryset = self.filter_queryset(self.get_queryset())

        if format_type == 'csv':
            content = ExportService.export_to_csv(queryset)
            response = HttpResponse(content, content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="data_items.csv"'
            return response

        if format_type in ('excel', 'xlsx'):
            try:
                excel_file = ExportService.export_to_excel(queryset)
            except ImportError:
                logger.exception('Excel export unavailable')
                return Response(
                    {'error': 'Excel export is unavailable on this server.'},
                    status=503,
                )
            response = HttpResponse(
                excel_file.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = 'attachment; filename="data_items.xlsx"'
            return response

        if format_type == 'json':
            content = ExportService.export_to_json(queryset)
            response = HttpResponse(content, content_type='application/json')
            response['Content-Disposition'] = 'attachment; filename="data_items.json"'
            return response

        return Response(
            {'error': f"Unsupported export format '{format_type}'. Use csv, json or excel."},
            status=400,
        )

    @action(detail=False, methods=['post'])
    def batch_operation(self, request: HttpRequest) -> Response:
        """
        Perform batch operations on filtered data items.
        Operations: update_status, update_priority, update_category,
                   add_tags, remove_tags, set_tags, delete
        """
        operation = request.data.get('operation')
        item_ids = request.data.get('item_ids', [])

        if not operation:
            return Response({'error': 'Operation is required'}, status=400)

        # Get queryset based on item_ids or filters
        if item_ids:
            queryset = DataItem.objects.filter(id__in=item_ids)
        else:
            queryset = self.filter_queryset(self.get_queryset())

        # 'operation' is passed positionally below, and 'item_ids' has already
        # been consumed. Forwarding the raw request body would hand the service
        # a second value for 'operation' and raise TypeError on every call.
        params = {
            key: value for key, value in request.data.items()
            if key not in ('operation', 'item_ids')
        }

        try:
            result = BatchOperationService.get_batch_operation_summary(
                operation, queryset, **params
            )
            return Response(result)
        except (ValueError, KeyError) as exc:
            # KeyError here means a required parameter for the operation is
            # missing — that is bad client input, not a server fault.
            return Response({'error': str(exc).strip("'")}, status=400)
        except Exception:
            logger.exception('Batch operation %r failed', operation)
            return Response({'error': 'Batch operation failed.'}, status=500)


class StorageFileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for StorageFile model.
    Handles file uploads, checksum verification, and storage tracking.
    """
    queryset = StorageFile.objects.select_related('data_item').all()
    filterset_fields = ['data_item', 'storage_location', 'status']
    search_fields = ['original_filename', 'checksum_sha256', 'notes']
    ordering_fields = ['created_at', 'file_size_bytes', 'last_verified_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        """Use upload serializer for creating files, full serializer otherwise."""
        if self.action == 'create':
            return StorageFileUploadSerializer
        return StorageFileSerializer

    @action(detail=True, methods=['post'])
    def verify(self, request: HttpRequest, pk: int = None) -> Response:
        """Verify file checksum integrity."""
        storage_file = self.get_object()
        checksum_type = request.data.get('checksum_type', 'sha256')

        if checksum_type not in ('md5', 'sha256'):
            return Response(
                {'error': "checksum_type must be 'md5' or 'sha256'."}, status=400
            )

        try:
            verified = storage_file.verify_checksum(checksum_type)
            return Response({
                'verified': verified,
                'status': storage_file.status,
                'last_verified_at': storage_file.last_verified_at,
                'error': storage_file.verification_error if not verified else None
            })
        except Exception:
            logger.exception('Checksum verification failed for StorageFile %s', pk)
            return Response({'error': 'Checksum verification failed.'}, status=500)

    @action(detail=True, methods=['post'])
    def calculate_checksum(self, request: HttpRequest, pk: int = None) -> Response:
        """Calculate file checksums."""
        storage_file = self.get_object()

        try:
            storage_file.calculate_checksums()
            storage_file.save(update_fields=[
                'checksum_md5', 'checksum_sha256', 'updated_at',
            ])
            return Response({
                'md5': storage_file.checksum_md5,
                'sha256': storage_file.checksum_sha256
            })
        except Exception:
            logger.exception('Checksum calculation failed for StorageFile %s', pk)
            return Response({'error': 'Checksum calculation failed.'}, status=500)

    @action(detail=False, methods=['get'])
    def by_status(self, request: HttpRequest) -> Response:
        """Get storage files grouped by status."""
        stats = StorageFile.objects.values('status').annotate(
            count=Count('id')
        ).order_by('-count')

        return Response(list(stats))


class TagViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Tag model.
    Provides CRUD operations and tag statistics.
    """
    serializer_class = TagSerializer
    filterset_fields = ['category']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    lookup_field = 'slug'

    def get_queryset(self):
        """Annotate the usage count the serializer reports (one query, not N+1)."""
        return Tag.objects.select_related('category').annotate(
            usage_count_annotated=Count('data_items', distinct=True)
        )

    @action(detail=True, methods=['get'])
    def items(self, request: HttpRequest, slug: str = None) -> Response:
        """Get all items with this tag."""
        tag = self.get_object()
        items = (
            tag.data_items
            .select_related('category', 'category__parent')
            .prefetch_related('tag_set')
        )
        page = self.paginate_queryset(items)
        if page is not None:
            return self.get_paginated_response(
                DataItemListSerializer(page, many=True).data
            )
        return Response(DataItemListSerializer(items, many=True).data)

    @action(detail=False, methods=['get'])
    def popular(self, request: HttpRequest) -> Response:
        """Get most popular tags by usage count."""
        tags = self.get_queryset().order_by('-usage_count_annotated', 'name')[:20]
        return Response(TagSerializer(tags, many=True).data)

    @action(detail=False, methods=['get'])
    def by_category(self, request: HttpRequest) -> Response:
        """Get tags grouped by category name."""
        tags_by_category: dict = {}

        # One pass over every tag rather than a query per category.
        for tag in self.get_queryset().order_by('category__name', 'name'):
            key = tag.category.name if tag.category_id else 'Uncategorized'
            tags_by_category.setdefault(key, []).append(TagSerializer(tag).data)

        return Response(tags_by_category)


class StorageProviderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for StorageProvider model.
    Provides CRUD operations and cost comparisons.
    """
    serializer_class = StorageProviderSerializer
    filterset_fields = ['provider_type', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'cost_per_gb_monthly', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        """Annotate the estimate count the serializer reports."""
        return StorageProvider.objects.annotate(
            estimate_count_annotated=Count('cost_estimates', distinct=True)
        )

    @action(detail=True, methods=['get'])
    def estimates(self, request: HttpRequest, pk: int = None) -> Response:
        """Get all cost estimates for this provider."""
        provider = self.get_object()
        estimates = provider.cost_estimates.filter(is_active=True)
        serializer = CostEstimateSerializer(estimates, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def compare(self, request: HttpRequest) -> Response:
        """Compare pricing across all active providers."""
        providers = self.filter_queryset(
            self.get_queryset().filter(is_active=True)
        )

        providers = providers.annotate(
            active_estimate_count=Count(
                'cost_estimates',
                filter=Q(cost_estimates__is_active=True),
                distinct=True,
            )
        )

        comparison = []
        for provider in providers:
            comparison.append({
                'id': provider.id,
                'name': provider.name,
                'provider_type': provider.get_provider_type_display(),
                'cost_per_gb_monthly': float(provider.cost_per_gb_monthly),
                'retrieval_cost_per_gb': float(provider.retrieval_cost_per_gb),
                'api_cost_per_1000_requests': float(provider.api_cost_per_1000_requests),
                'estimate_count': provider.active_estimate_count,
            })

        # Sort by cost per GB
        comparison.sort(key=lambda x: x['cost_per_gb_monthly'])

        return Response(comparison)

    @action(detail=False, methods=['post'])
    def calculate_estimate(self, request: HttpRequest) -> Response:
        """Calculate estimated costs for given size across all providers."""
        size_gb = request.data.get('size_gb')
        retrieval_frequency = request.data.get('retrieval_frequency', 0)  # times per year

        if not size_gb:
            return Response({'error': 'size_gb is required'}, status=400)

        try:
            size_gb = float(size_gb)
            retrieval_frequency = float(retrieval_frequency)
        except (ValueError, TypeError):
            return Response({'error': 'Invalid numeric values'}, status=400)

        providers = self.filter_queryset(
            self.get_queryset().filter(is_active=True)
        )

        estimates = []
        for provider in providers:
            monthly_storage = float(provider.cost_per_gb_monthly) * size_gb
            annual_storage = monthly_storage * 12
            retrieval_cost = float(provider.retrieval_cost_per_gb) * size_gb * retrieval_frequency
            total_first_year = annual_storage + retrieval_cost

            estimates.append({
                'provider_id': provider.id,
                'provider_name': provider.name,
                'provider_type': provider.get_provider_type_display(),
                'monthly_storage_cost': round(monthly_storage, 2),
                'annual_storage_cost': round(annual_storage, 2),
                'estimated_retrieval_cost': round(retrieval_cost, 2),
                'total_first_year_cost': round(total_first_year, 2)
            })

        # Sort by total first year cost
        estimates.sort(key=lambda x: x['total_first_year_cost'])

        return Response({
            'size_gb': size_gb,
            'retrieval_frequency': retrieval_frequency,
            'estimates': estimates
        })


class CostEstimateViewSet(viewsets.ModelViewSet):
    """
    ViewSet for CostEstimate model.
    Provides CRUD operations and cost analysis.
    """
    queryset = CostEstimate.objects.select_related('data_item', 'provider').all()
    serializer_class = CostEstimateSerializer
    filterset_fields = ['data_item', 'provider', 'is_active']
    search_fields = ['data_item__name', 'provider__name', 'notes']
    ordering_fields = ['created_at', 'monthly_storage_cost', 'annual_storage_cost']
    ordering = ['-created_at']

    @action(detail=True, methods=['post'])
    def recalculate(self, request: HttpRequest, pk: int = None) -> Response:
        """Recalculate costs for this estimate."""
        estimate = self.get_object()
        estimate.calculate_costs()
        estimate.save()

        serializer = CostEstimateSerializer(estimate)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def bulk_recalculate(self, request: HttpRequest) -> Response:
        """Recalculate costs for all active estimates."""
        queryset = self.filter_queryset(
            self.get_queryset().filter(is_active=True)
        )

        updated = 0
        for estimate in queryset:
            estimate.calculate_costs()
            estimate.save()
            updated += 1

        return Response({
            'message': f'Recalculated costs for {updated} estimate(s)',
            'updated_count': updated
        })

    @action(detail=False, methods=['get'])
    def summary(self, request: HttpRequest) -> Response:
        """Get summary of all cost estimates."""


        queryset = self.filter_queryset(
            self.get_queryset().filter(is_active=True)
        )

        stats = queryset.aggregate(
            total_estimates=Count('id'),
            total_monthly_cost=Sum('monthly_storage_cost'),
            total_annual_cost=Sum('annual_storage_cost'),
            avg_monthly_cost=Avg('monthly_storage_cost'),
            total_estimated_size=Sum('estimated_size_gb')
        )

        # Get breakdown by provider
        by_provider = queryset.values(
            'provider__name', 'provider__provider_type'
        ).annotate(
            estimate_count=Count('id'),
            total_monthly=Sum('monthly_storage_cost'),
            total_annual=Sum('annual_storage_cost'),
            total_size=Sum('estimated_size_gb')
        ).order_by('-total_annual')

        return Response({
            'summary': {
                'total_estimates': stats['total_estimates'] or 0,
                'total_monthly_cost': float(stats['total_monthly_cost'] or 0),
                'total_annual_cost': float(stats['total_annual_cost'] or 0),
                'average_monthly_cost': float(stats['avg_monthly_cost'] or 0),
                'total_estimated_size_gb': float(stats['total_estimated_size'] or 0)
            },
            'by_provider': list(by_provider)
        })

    @action(detail=False, methods=['get'])
    def comparison(self, request: HttpRequest) -> Response:
        """Compare costs across providers for same data items."""
        data_item_id = request.query_params.get('data_item')

        if not data_item_id:
            return Response({'error': 'data_item parameter is required'}, status=400)

        estimates = self.get_queryset().filter(
            data_item_id=data_item_id,
            is_active=True
        ).select_related('provider', 'data_item')

        if not estimates.exists():
            return Response({'error': 'No estimates found for this data item'}, status=404)

        serializer = CostEstimateSerializer(estimates, many=True)

        # Find cheapest option
        cheapest = min(estimates, key=lambda e: e.get_total_first_year_cost())

        return Response({
            'data_item': {
                'id': estimates.first().data_item.id,
                'name': estimates.first().data_item.name
            },
            'estimates': serializer.data,
            'cheapest_provider': {
                'id': cheapest.provider.id,
                'name': cheapest.provider.name,
                'total_first_year_cost': cheapest.get_total_first_year_cost()
            }
        })


@require_http_methods(["GET", "POST"])
def index(request: HttpRequest) -> HttpResponse:
    """
    Main index view.
    Displays list of items and form for adding new items.
    """
    if request.method == 'POST':
        # Reads stay open (matching the API's IsAuthenticatedOrReadOnly), but
        # writes must not be. Without this an anonymous visitor can create
        # items through the web form while the API correctly refuses them.
        if not request.user.is_authenticated:
            messages.error(request, 'You must be signed in to add items.')
            return redirect_to_login(request.get_full_path())

        form = DataItemForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Data item added successfully!')
                return redirect('index')
            except Exception:
                logger.exception('Failed to save DataItem from web form')
                messages.error(request, 'Error adding item. Please try again.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = DataItemForm()

    # Get filter form and apply filters
    filter_form = DataItemFilterForm(request.GET)
    items = DataItem.objects.select_related('category').prefetch_related('tag_set')

    if filter_form.is_valid():
        items = filter_form.filter_queryset(items)

    items = items.order_by('-updated_at')

    context = {
        'form': form,
        'filter_form': filter_form,
        'items': items,
        'categories': Category.objects.all().order_by('name'),
    }
    return render(request, 'index.html', context)


@login_required
@require_http_methods(["POST"])
def import_json(request: HttpRequest) -> HttpResponse:
    """
    Import data items from uploaded JSON file.
    Uses JSONImportService to handle the import logic.

    Requires authentication: this creates items and auto-creates categories in
    bulk, which anonymous visitors must not be able to do.
    """
    form = JSONImportForm(request.POST, request.FILES)

    if not form.is_valid():
        for error in form.errors.get('json_file', []):
            messages.error(request, error)
        return redirect('index')

    try:
        file = request.FILES['json_file']
        result = JSONImportService.import_from_json(file)

        # Report results
        if result.success:
            messages.success(
                request,
                f'Successfully imported {result.imported_count} items.'
            )

        if result.errors:
            error_summary = result.get_error_summary()
            if result.imported_count > 0:
                messages.warning(request, error_summary)
            else:
                messages.error(request, 'No items were imported due to errors.')
                messages.error(request, error_summary)

    except Exception as e:
        messages.error(request, "Unexpected error during import.")

    return redirect('index')


@require_http_methods(["GET"])
def dashboard(request: HttpRequest) -> HttpResponse:
    """
    Dashboard view with data visualization and statistics.
    """
    stats = DataItemService.get_statistics()
    category_stats = DataItemService.get_category_statistics()

    context = {
        'total_items': stats['total_items'],
        'total_categories': Category.objects.count(),
        'total_size_gb': stats['total_size_gb'],
        'average_size_gb': stats['average_size_gb'],
        'status_breakdown': stats['status_breakdown'],
        'priority_breakdown': stats['priority_breakdown'],
        'category_stats': category_stats,
    }

    return render(request, 'dashboard.html', context)
