import hashlib
import os
from django.db import models
from django.core.validators import MinValueValidator
from django.urls import reverse
from django.conf import settings


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


class StorageFile(models.Model):
    """
    Represents a physical file associated with a data item.
    Tracks file location, checksums, and verification status.
    """
    data_item = models.ForeignKey(
        DataItem,
        on_delete=models.CASCADE,
        related_name='storage_files',
        help_text="Data item this file belongs to"
    )
    file = models.FileField(
        upload_to='storage_files/%Y/%m/%d/',
        blank=True,
        null=True,
        help_text="Uploaded file (optional if tracking external storage)"
    )
    file_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Path to file (local or remote)"
    )
    original_filename = models.CharField(
        max_length=255,
        help_text="Original filename"
    )
    file_size_bytes = models.BigIntegerField(
        help_text="File size in bytes",
        validators=[MinValueValidator(0)]
    )

    # Checksums for verification
    checksum_md5 = models.CharField(
        max_length=32,
        blank=True,
        help_text="MD5 checksum (32 hex chars)"
    )
    checksum_sha256 = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 checksum (64 hex chars)"
    )

    # Storage information
    storage_location = models.CharField(
        max_length=50,
        choices=[
            ('local', 'Local Storage'),
            ('nas', 'Network Attached Storage'),
            ('s3', 'Amazon S3'),
            ('glacier', 'Amazon Glacier'),
            ('gcs', 'Google Cloud Storage'),
            ('azure', 'Azure Blob Storage'),
            ('backblaze', 'Backblaze B2'),
            ('other', 'Other'),
        ],
        default='local',
        help_text="Where the file is stored"
    )
    storage_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Full path or URL to the stored file"
    )

    # Verification status
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('uploading', 'Uploading'),
            ('stored', 'Stored'),
            ('verified', 'Verified'),
            ('corrupted', 'Corrupted'),
            ('missing', 'Missing'),
        ],
        default='pending',
        help_text="Current file status"
    )
    last_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the file was last verified"
    )
    verification_error = models.TextField(
        blank=True,
        help_text="Error message if verification failed"
    )

    # Metadata
    mime_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="MIME type of the file"
    )
    notes = models.TextField(
        blank=True,
        help_text="Additional notes about this file"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['data_item', 'status']),
            models.Index(fields=['checksum_sha256']),
            models.Index(fields=['storage_location']),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.get_storage_location_display()})"

    def get_file_size_display(self):
        """Returns human-readable file size"""
        size_bytes = self.file_size_bytes

        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def calculate_checksums(self, file_obj=None):
        """
        Calculate MD5 and SHA-256 checksums for the file.
        Uses the uploaded file or reads from storage_path.
        """
        if file_obj is None and self.file:
            file_obj = self.file.open('rb')
        elif file_obj is None and self.storage_path and os.path.exists(self.storage_path):
            file_obj = open(self.storage_path, 'rb')
        elif file_obj is None:
            raise ValueError("No file available for checksum calculation")

        md5_hash = hashlib.md5()
        sha256_hash = hashlib.sha256()

        # Read file in chunks to handle large files
        for chunk in iter(lambda: file_obj.read(8192), b''):
            md5_hash.update(chunk)
            sha256_hash.update(chunk)

        self.checksum_md5 = md5_hash.hexdigest()
        self.checksum_sha256 = sha256_hash.hexdigest()

        # Close file if we opened it
        if hasattr(file_obj, 'close'):
            file_obj.close()

    def verify_checksum(self, checksum_type='sha256'):
        """
        Verify file integrity by recalculating checksum.
        Returns True if checksum matches, False otherwise.
        """
        from django.utils import timezone

        try:
            # Store original checksums
            original_md5 = self.checksum_md5
            original_sha256 = self.checksum_sha256

            # Recalculate checksums
            self.calculate_checksums()

            # Check if they match
            if checksum_type == 'md5':
                verified = self.checksum_md5 == original_md5
            else:  # sha256
                verified = self.checksum_sha256 == original_sha256

            # Update status
            self.last_verified_at = timezone.now()
            if verified:
                self.status = 'verified'
                self.verification_error = ''
            else:
                self.status = 'corrupted'
                self.verification_error = f'{checksum_type.upper()} checksum mismatch'

            self.save()
            return verified

        except Exception as e:
            self.status = 'corrupted'
            self.verification_error = str(e)
            self.last_verified_at = timezone.now()
            self.save()
            return False

    def get_absolute_url(self):
        """Returns URL for this file (useful for future detail views)"""
        return reverse('storagefile-detail', kwargs={'pk': self.pk})