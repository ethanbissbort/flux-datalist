"""
Views for the Cold Storage app.
Handles both REST API endpoints and traditional template-based views.
"""
from typing import Any, Dict
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.db.models import QuerySet
from django.views.decorators.http import require_http_methods

from .models import (
    DataItem, Category, StorageFile, Tag,
    StorageProvider, CostEstimate
)
from .serializers import (
    CategorySerializer, DataItemSerializer,
    DataItemListSerializer, DataItemWriteSerializer,
    DataItemWithTagsSerializer, StorageFileSerializer,
    StorageFileUploadSerializer, TagSerializer,
    StorageProviderSerializer, CostEstimateSerializer
)
from .forms import DataItemForm, JSONImportForm, DataItemFilterForm
from .services import (
    JSONImportService, DataItemService, ExportService,
    BatchOperationService
)


class CategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Category model.
    Provides CRUD operations via REST API.
    """
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filterset_fields = ['parent']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

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
        from django.db.models import Sum, Count
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
        """Export categories in various formats."""
        format_type = request.query_params.get('format', 'json').lower()
        queryset = self.filter_queryset(self.get_queryset())

        if format_type == 'csv':
            content = ExportService.export_categories_to_csv(queryset)
            response = HttpResponse(content, content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="categories.csv"'
            return response
        else:  # json
            content = ExportService.export_categories_to_json(queryset)
            response = HttpResponse(content, content_type='application/json')
            response['Content-Disposition'] = 'attachment; filename="categories.json"'
            return response


class DataItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for DataItem model.
    Provides CRUD operations via REST API with different serializers for read/write.
    """
    queryset = DataItem.objects.select_related('category').all()
    filterset_fields = ['category', 'status', 'priority']
    search_fields = ['name', 'tags', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at', 'size_estimate_gb']
    ordering = ['-updated_at']

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
        """Export data items in various formats (CSV, JSON, Excel)."""
        format_type = request.query_params.get('format', 'json').lower()
        queryset = self.filter_queryset(self.get_queryset())

        if format_type == 'csv':
            content = ExportService.export_to_csv(queryset)
            response = HttpResponse(content, content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="data_items.csv"'
            return response
        elif format_type == 'excel' or format_type == 'xlsx':
            try:
                excel_file = ExportService.export_to_excel(queryset)
                response = HttpResponse(
                    excel_file.getvalue(),
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
                response['Content-Disposition'] = 'attachment; filename="data_items.xlsx"'
                return response
            except ImportError as e:
                return HttpResponse(str(e), status=500)
        else:  # json
            content = ExportService.export_to_json(queryset)
            response = HttpResponse(content, content_type='application/json')
            response['Content-Disposition'] = 'attachment; filename="data_items.json"'
            return response

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

        try:
            result = BatchOperationService.get_batch_operation_summary(
                operation, queryset, **request.data
            )
            return Response(result)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            return Response({'error': f'Operation failed: {str(e)}'}, status=500)


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

        try:
            verified = storage_file.verify_checksum(checksum_type)
            return Response({
                'verified': verified,
                'status': storage_file.status,
                'last_verified_at': storage_file.last_verified_at,
                'error': storage_file.verification_error if not verified else None
            })
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=True, methods=['post'])
    def calculate_checksum(self, request: HttpRequest, pk: int = None) -> Response:
        """Calculate file checksums."""
        storage_file = self.get_object()

        try:
            storage_file.calculate_checksums()
            storage_file.save()
            return Response({
                'md5': storage_file.checksum_md5,
                'sha256': storage_file.checksum_sha256
            })
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['get'])
    def by_status(self, request: HttpRequest) -> Response:
        """Get storage files grouped by status."""
        from django.db.models import Count

        stats = StorageFile.objects.values('status').annotate(
            count=Count('id')
        ).order_by('-count')

        return Response(list(stats))


class TagViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Tag model.
    Provides CRUD operations and tag statistics.
    """
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    filterset_fields = ['category']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    lookup_field = 'slug'

    @action(detail=True, methods=['get'])
    def items(self, request: HttpRequest, slug: str = None) -> Response:
        """Get all items with this tag."""
        tag = self.get_object()
        items = tag.data_items.all()
        serializer = DataItemListSerializer(items, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def popular(self, request: HttpRequest) -> Response:
        """Get most popular tags by usage count."""
        from django.db.models import Count

        tags = Tag.objects.annotate(
            usage_count=Count('data_items')
        ).order_by('-usage_count')[:20]

        serializer = TagSerializer(tags, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_category(self, request: HttpRequest) -> Response:
        """Get tags grouped by category."""
        from django.db.models import Count

        tags_by_category = {}
        categories = Category.objects.all()

        for category in categories:
            category_tags = Tag.objects.filter(category=category).annotate(
                usage_count=Count('data_items')
            ).order_by('name')

            if category_tags.exists():
                tags_by_category[category.name] = TagSerializer(category_tags, many=True).data

        # Include uncategorized tags
        uncategorized = Tag.objects.filter(category__isnull=True).annotate(
            usage_count=Count('data_items')
        ).order_by('name')

        if uncategorized.exists():
            tags_by_category['Uncategorized'] = TagSerializer(uncategorized, many=True).data

        return Response(tags_by_category)


class StorageProviderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for StorageProvider model.
    Provides CRUD operations and cost comparisons.
    """
    queryset = StorageProvider.objects.all()
    serializer_class = StorageProviderSerializer
    filterset_fields = ['provider_type', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'cost_per_gb_monthly', 'created_at']
    ordering = ['name']

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

        comparison = []
        for provider in providers:
            comparison.append({
                'id': provider.id,
                'name': provider.name,
                'provider_type': provider.get_provider_type_display(),
                'cost_per_gb_monthly': float(provider.cost_per_gb_monthly),
                'retrieval_cost_per_gb': float(provider.retrieval_cost_per_gb),
                'api_cost_per_1000_requests': float(provider.api_cost_per_1000_requests),
                'estimate_count': provider.cost_estimates.filter(is_active=True).count()
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
        from django.db.models import Sum, Avg, Count

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
        form = DataItemForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Data item added successfully!')
                return redirect('index')
            except Exception as e:
                messages.error(request, f'Error adding item: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = DataItemForm()

    # Get filter form and apply filters
    filter_form = DataItemFilterForm(request.GET)
    items = DataItem.objects.select_related('category').all()

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


@require_http_methods(["POST"])
def import_json(request: HttpRequest) -> HttpResponse:
    """
    Import data items from uploaded JSON file.
    Uses JSONImportService to handle the import logic.
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
        messages.error(request, f'Unexpected error during import: {str(e)}')

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
