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

from .models import DataItem, Category, StorageFile
from .serializers import (
    CategorySerializer, DataItemSerializer,
    DataItemListSerializer, DataItemWriteSerializer,
    StorageFileSerializer, StorageFileUploadSerializer
)
from .forms import DataItemForm, JSONImportForm, DataItemFilterForm
from .services import JSONImportService, DataItemService, ExportService


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
