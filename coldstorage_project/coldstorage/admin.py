"""
Django admin configuration for Cold Storage app.
Provides enhanced admin interface for managing categories and data items.
"""
from typing import Optional
from django.contrib import admin
from django.db.models import QuerySet, Sum
from django.http import HttpRequest
from django.utils.html import format_html
from .models import Category, DataItem, StorageFile


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Enhanced admin for Category model."""

    list_display = ('name', 'parent', 'item_count', 'children_count', 'created_at')
    list_filter = ('parent', 'created_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'parent')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('created_at', 'updated_at')

    def item_count(self, obj: Category) -> int:
        """Display number of items in this category."""
        return obj.data_items.count()
    item_count.short_description = 'Items'

    def children_count(self, obj: Category) -> int:
        """Display number of child categories."""
        return obj.children.count()
    children_count.short_description = 'Sub-categories'


@admin.register(DataItem)
class DataItemAdmin(admin.ModelAdmin):
    """Enhanced admin for DataItem model."""

    list_display = (
        'name', 'category', 'subcategory', 'size_display',
        'priority_badge', 'status_badge', 'updated_at'
    )
    list_filter = (
        'category', 'priority', 'status', 'created_at', 'updated_at'
    )
    search_fields = ('name', 'tags', 'description', 'examples', 'notes')
    ordering = ('-updated_at', 'name')
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'category', 'subcategory', 'description')
        }),
        ('Storage Details', {
            'fields': ('size_estimate_gb', 'examples', 'tags')
        }),
        ('Source Information', {
            'fields': ('source_url', 'notes')
        }),
        ('Status & Priority', {
            'fields': ('status', 'priority')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('created_at', 'updated_at')

    actions = ['mark_as_acquired', 'mark_as_stored', 'mark_as_verified', 'set_high_priority']

    def size_display(self, obj: DataItem) -> str:
        """Display human-readable size."""
        return obj.get_size_display()
    size_display.short_description = 'Size'
    size_display.admin_order_field = 'size_estimate_gb'

    def priority_badge(self, obj: DataItem) -> str:
        """Display priority with color coding."""
        colors = {
            'low': '#6c757d',
            'medium': '#0d6efd',
            'high': '#fd7e14',
            'critical': '#dc3545',
        }
        color = colors.get(obj.priority, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            color, obj.get_priority_display()
        )
    priority_badge.short_description = 'Priority'
    priority_badge.admin_order_field = 'priority'

    def status_badge(self, obj: DataItem) -> str:
        """Display status with color coding."""
        colors = {
            'planned': '#6c757d',
            'in_progress': '#0d6efd',
            'acquired': '#ffc107',
            'stored': '#198754',
            'verified': '#20c997',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'

    # Admin actions
    def mark_as_acquired(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Mark selected items as acquired."""
        updated = queryset.update(status='acquired')
        self.message_user(request, f'{updated} item(s) marked as acquired.')
    mark_as_acquired.short_description = 'Mark as Acquired'

    def mark_as_stored(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Mark selected items as stored."""
        updated = queryset.update(status='stored')
        self.message_user(request, f'{updated} item(s) marked as stored.')
    mark_as_stored.short_description = 'Mark as Stored'

    def mark_as_verified(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Mark selected items as verified."""
        updated = queryset.update(status='verified')
        self.message_user(request, f'{updated} item(s) marked as verified.')
    mark_as_verified.short_description = 'Mark as Verified'

    def set_high_priority(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Set selected items to high priority."""
        updated = queryset.update(priority='high')
        self.message_user(request, f'{updated} item(s) set to high priority.')
    set_high_priority.short_description = 'Set High Priority'


@admin.register(StorageFile)
class StorageFileAdmin(admin.ModelAdmin):
    """Enhanced admin for StorageFile model."""

    list_display = (
        'original_filename', 'data_item', 'file_size_display',
        'storage_location_badge', 'status_badge', 'last_verified_at'
    )
    list_filter = (
        'storage_location', 'status', 'created_at', 'last_verified_at'
    )
    search_fields = ('original_filename', 'data_item__name', 'checksum_sha256', 'notes')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'

    fieldsets = (
        ('File Information', {
            'fields': ('data_item', 'file', 'original_filename', 'file_size_bytes', 'mime_type')
        }),
        ('Storage Details', {
            'fields': ('storage_location', 'storage_path', 'file_path')
        }),
        ('Checksums', {
            'fields': ('checksum_md5', 'checksum_sha256'),
            'classes': ('collapse',)
        }),
        ('Verification', {
            'fields': ('status', 'last_verified_at', 'verification_error')
        }),
        ('Additional Information', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = (
        'checksum_md5', 'checksum_sha256', 'last_verified_at',
        'verification_error', 'created_at', 'updated_at'
    )

    actions = ['verify_checksums', 'mark_as_verified', 'calculate_checksums']

    def file_size_display(self, obj: StorageFile) -> str:
        """Display human-readable file size."""
        return obj.get_file_size_display()
    file_size_display.short_description = 'Size'
    file_size_display.admin_order_field = 'file_size_bytes'

    def storage_location_badge(self, obj: StorageFile) -> str:
        """Display storage location with color coding."""
        colors = {
            'local': '#0d6efd',
            'nas': '#198754',
            's3': '#fd7e14',
            'glacier': '#6c757d',
            'gcs': '#0dcaf0',
            'azure': '#0d6efd',
            'backblaze': '#dc3545',
            'other': '#6c757d',
        }
        color = colors.get(obj.storage_location, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px;">{}</span>',
            color, obj.get_storage_location_display()
        )
    storage_location_badge.short_description = 'Storage'
    storage_location_badge.admin_order_field = 'storage_location'

    def status_badge(self, obj: StorageFile) -> str:
        """Display status with color coding."""
        colors = {
            'pending': '#6c757d',
            'uploading': '#0d6efd',
            'stored': '#198754',
            'verified': '#20c997',
            'corrupted': '#dc3545',
            'missing': '#ffc107',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'

    # Admin actions
    def verify_checksums(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Verify checksums for selected files."""
        verified_count = 0
        failed_count = 0

        for storage_file in queryset:
            try:
                if storage_file.verify_checksum():
                    verified_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

        if verified_count > 0:
            self.message_user(request, f'{verified_count} file(s) verified successfully.')
        if failed_count > 0:
            self.message_user(
                request,
                f'{failed_count} file(s) failed verification.',
                level='warning'
            )
    verify_checksums.short_description = 'Verify file checksums'

    def mark_as_verified(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Mark selected files as verified without checking."""
        from django.utils import timezone
        updated = queryset.update(status='verified', last_verified_at=timezone.now())
        self.message_user(request, f'{updated} file(s) marked as verified.')
    mark_as_verified.short_description = 'Mark as Verified (no check)'

    def calculate_checksums(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Calculate checksums for selected files."""
        calculated_count = 0
        failed_count = 0

        for storage_file in queryset:
            try:
                storage_file.calculate_checksums()
                storage_file.save()
                calculated_count += 1
            except Exception:
                failed_count += 1

        if calculated_count > 0:
            self.message_user(request, f'Calculated checksums for {calculated_count} file(s).')
        if failed_count > 0:
            self.message_user(
                request,
                f'Failed to calculate checksums for {failed_count} file(s).',
                level='warning'
            )
    calculate_checksums.short_description = 'Calculate checksums'


# Customize admin site header and title
admin.site.site_header = 'Cold Storage Administration'
admin.site.site_title = 'Cold Storage Admin'
admin.site.index_title = 'Cold Storage Data Management'
