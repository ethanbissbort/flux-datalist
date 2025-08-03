from django.db import models
from django.core.validators import MinValueValidator
from django.urls import reverse


class Category(models.Model):
    """
    Hierarchical category system for organizing data items.
    Supports parent-child relationships for nested categorization.
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, help_text="Optional description of this category")
    parent = models.ForeignKey(
        'self', 
        null=True, 
        blank=True, 
        on_delete=models.CASCADE,
        related_name='children',
        help_text="Parent category for hierarchical organization"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name

    def get_full_path(self):
        """Returns the full hierarchical path of the category"""
        path = [self.name]
        parent = self.parent
        while parent:
            path.insert(0, parent.name)
            parent = parent.parent
        return " > ".join(path)

    def get_descendants(self):
        """Returns all descendant categories"""
        descendants = []
        for child in self.children.all():
            descendants.append(child)
            descendants.extend(child.get_descendants())
        return descendants


class DataItem(models.Model):
    """
    Represents a data item to be stored in cold storage.
    Contains metadata, size estimates, and categorization.
    """
    name = models.CharField(max_length=200, help_text="Name or title of the data item")
    category = models.ForeignKey(
        Category, 
        on_delete=models.CASCADE,
        related_name='data_items',
        help_text="Primary category for this item"
    )
    subcategory = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Optional subcategory (e.g., 'Indie', 'AAA', 'Documentary')"
    )
    description = models.TextField(blank=True, help_text="Detailed description of the item")
    examples = models.TextField(
        blank=True, 
        help_text="Specific examples or instances of this item"
    )
    size_estimate_gb = models.FloatField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(0.0)],
        help_text="Estimated storage size in gigabytes"
    )
    tags = models.CharField(
        max_length=250, 
        blank=True,
        help_text="Comma-separated tags for filtering and search"
    )
    source_url = models.URLField(
        blank=True,
        help_text="URL where this data can be obtained"
    )
    notes = models.TextField(
        blank=True,
        help_text="Additional notes, acquisition status, or special instructions"
    )
    
    # Metadata fields
    priority = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical'),
        ],
        default='medium',
        help_text="Storage priority level"
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('planned', 'Planned'),
            ('in_progress', 'In Progress'),
            ('acquired', 'Acquired'),
            ('stored', 'Stored'),
            ('verified', 'Verified'),
        ],
        default='planned',
        help_text="Current acquisition/storage status"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', 'name']
        indexes = [
            models.Index(fields=['category', 'subcategory']),
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['size_estimate_gb']),
        ]

    def __str__(self):
        if self.subcategory:
            return f"{self.name} ({self.subcategory})"
        return self.name

    def get_tags_list(self):
        """Returns tags as a list, handling empty strings"""
        if not self.tags.strip():
            return []
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]

    def get_size_display(self):
        """Returns human-readable size format"""
        if not self.size_estimate_gb:
            return "Unknown"
        
        size = self.size_estimate_gb
        if size < 1:
            return f"{size * 1000:.0f} MB"
        elif size < 1000:
            return f"{size:.1f} GB"
        else:
            return f"{size / 1000:.1f} TB"

    def get_absolute_url(self):
        """Returns URL for this item (useful for future detail views)"""
        return reverse('dataitem-detail', kwargs={'pk': self.pk})

    @classmethod
    def get_total_size(cls):
        """Returns total estimated size across all items"""
        from django.db.models import Sum
        total = cls.objects.aggregate(Sum('size_estimate_gb'))['size_estimate_gb__sum']
        return total or 0

    @classmethod
    def get_category_sizes(cls):
        """Returns size breakdown by category"""
        from django.db.models import Sum
        return cls.objects.values('category__name').annotate(
            total_size=Sum('size_estimate_gb')
        ).order_by('-total_size')