"""
Django admin configuration for Cold Storage app.
Provides enhanced admin interface for managing categories and data items.
"""
from typing import Optional
from django.contrib import admin
from django.db.models import QuerySet, Sum
from django.http import HttpRequest
from django.utils.html import format_html
from .models import Category, DataItem


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


# Customize admin site header and title
admin.site.site_header = 'Cold Storage Administration'
admin.site.site_title = 'Cold Storage Admin'
admin.site.index_title = 'Cold Storage Data Management'
