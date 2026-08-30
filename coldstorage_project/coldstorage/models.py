import hashlib
import os
from django.db import models
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.validators import MinValueValidator
from django.urls import reverse
from django.conf import settings


# Category trees are only ever a handful of levels deep in practice, so a walk
# that gets this far is corrupt data rather than a legitimate hierarchy.
MAX_CATEGORY_DEPTH = 100

# Stands in for the part of a path that cannot be walked because the rows form
# a cycle: a poisoned row stays readable so an operator can go and fix it.
CYCLE_MARKER = '[cycle]'


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
        """
        Returns the full hierarchical path of the category.

        The walk is bounded by a visited set and MAX_CATEGORY_DEPTH: a row that
        is already part of a parent cycle must stay readable instead of pinning
        a worker at 100% CPU forever.
        """
        path = [self.name]
        visited = {self.pk} if self.pk is not None else set()
        parent = self.parent
        depth = 0

        while parent is not None:
            if depth >= MAX_CATEGORY_DEPTH or parent.pk in visited:
                # Degrade gracefully rather than raising.
                path.insert(0, CYCLE_MARKER)
                break
            visited.add(parent.pk)
            path.insert(0, parent.name)
            parent = parent.parent
            depth += 1

        return " > ".join(path)

    def get_descendants(self):
        """
        Returns all descendant categories, depth-first and pre-order.

        Iterative, with a visited set and a depth cap, so a cyclic row cannot
        recurse forever; every category is returned at most once.
        """
        descendants = []
        if self.pk is None:
            return descendants

        visited = {self.pk}
        stack = [(child, 1) for child in reversed(list(self.children.all()))]

        while stack:
            node, depth = stack.pop()
            if node.pk in visited:
                continue
            visited.add(node.pk)
            descendants.append(node)
            if depth < MAX_CATEGORY_DEPTH:
                stack.extend(
                    (child, depth + 1)
                    for child in reversed(list(node.children.all()))
                )

        return descendants

    def would_create_cycle(self, parent) -> bool:
        """
        Return True if assigning ``parent`` to this category would create a
        circular reference (including making the category its own parent).

        The ancestor walk is itself bounded by a visited set and
        MAX_CATEGORY_DEPTH, so it stays safe when the stored rows are already
        corrupt. A chain that is already cyclic, or absurdly deep, is reported
        as unsafe too: attaching to it would poison this row as well.
        """
        if parent is None:
            return False
        if parent is self:
            return True
        if self.pk is None:
            # An unsaved category cannot yet be anybody's ancestor.
            return False

        visited = set()
        current = parent
        depth = 0

        while current is not None:
            if current.pk is not None and current.pk == self.pk:
                return True
            key = current.pk if current.pk is not None else ('obj', id(current))
            if key in visited:
                return True
            visited.add(key)
            depth += 1
            if depth > MAX_CATEGORY_DEPTH:
                return True
            current = current.parent

        return False

    def clean(self):
        """Reject a parent assignment that would create a circular reference."""
        super().clean()
        if self.would_create_cycle(self.parent):
            raise ValidationError(
                'Cannot set parent: would create a circular reference.'
            )


class Tag(models.Model):
    """
    Tags for organizing and categorizing data items.
    Supports color coding and optional category grouping.
    """
    name = models.CharField(
        max_length=50,
        unique=True,
        help_text="Tag name (e.g., 'Linux', 'Open Source', 'Media')"
    )
    slug = models.SlugField(
        max_length=50,
        unique=True,
        help_text="URL-friendly version of name"
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of this tag"
    )
    color = models.CharField(
        max_length=7,
        default='#6c757d',
        help_text="Hex color code for UI display (e.g., #FF5733)"
    )
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tags',
        help_text="Optional category grouping"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Auto-generate slug from name if not provided."""
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_usage_count(self):
        """Returns number of data items using this tag."""
        return self.data_items.count()


class StorageProvider(models.Model):
    """
    Storage provider information and pricing.
    Used for cost estimation and tracking.
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Provider name (e.g., 'AWS S3', 'Google Cloud Storage')"
    )
    provider_type = models.CharField(
        max_length=50,
        choices=[
            ('local', 'Local Storage'),
            ('nas', 'Network Attached Storage'),
            ('cloud_hot', 'Cloud Storage (Hot)'),
            ('cloud_warm', 'Cloud Storage (Warm)'),
            ('cloud_cold', 'Cloud Storage (Cold/Archive)'),
            ('tape', 'Tape Storage'),
            ('other', 'Other'),
        ],
        default='cloud_hot',
        help_text="Type of storage provider"
    )

    # Pricing information
    cost_per_gb_monthly = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text="Monthly cost per GB (e.g., $0.023000)"
    )
    retrieval_cost_per_gb = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text="Cost per GB for data retrieval (e.g., $0.090000)"
    )
    api_cost_per_1000_requests = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text="Cost per 1000 API requests"
    )

    # Provider details
    description = models.TextField(
        blank=True,
        help_text="Provider description and notes"
    )
    url = models.URLField(
        blank=True,
        help_text="Provider website URL"
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this provider is currently in use"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"

    def calculate_monthly_cost(self, size_gb):
        """Calculate monthly cost for given storage size."""
        return float(self.cost_per_gb_monthly) * size_gb

    def calculate_retrieval_cost(self, size_gb):
        """Calculate one-time retrieval cost for given size."""
        return float(self.retrieval_cost_per_gb) * size_gb


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

    # Tags - M2M relationship
    tag_set = models.ManyToManyField(
        Tag,
        blank=True,
        related_name='data_items',
        help_text="Tags for categorization and filtering"
    )

    # Legacy tags field (kept for migration, will be deprecated)
    tags_old = models.CharField(
        max_length=250,
        blank=True,
        help_text="[DEPRECATED] Old comma-separated tags (migrating to tag_set)"
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
        """Returns tags as a list of tag names"""
        return [tag.name for tag in self.tag_set.all()]

    def get_tags_display(self):
        """Returns comma-separated list of tag names"""
        return ', '.join(self.get_tags_list())

    def add_tags_from_string(self, tags_string):
        """
        Add tags from a comma-separated string.
        Creates tags if they don't exist.
        """
        if not tags_string:
            return

        tag_names = [t.strip() for t in tags_string.split(',') if t.strip()]
        for tag_name in tag_names:
            tag, created = Tag.objects.get_or_create(name=tag_name)
            self.tag_set.add(tag)

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

    def _resolve_storage_path(self):
        """
        Resolve ``storage_path`` to a real path confined to the allowed roots.

        ``storage_path`` is free-form input from the API and the admin, so it is
        untrusted: without this check any authenticated user could make the
        worker read - and fingerprint by digest - arbitrary server files.
        """
        raw = (self.storage_path or '').strip()
        if not raw:
            raise ValueError("No file available for checksum calculation")

        roots = getattr(settings, 'COLDSTORAGE_ALLOWED_STORAGE_ROOTS', None) or [
            settings.MEDIA_ROOT
        ]
        if isinstance(roots, (str, os.PathLike)):
            roots = [roots]

        # realpath() collapses '..' segments and follows symlinks, so neither a
        # traversal nor a symlink planted inside an allowed root can escape.
        candidate = os.path.realpath(raw)

        for root in roots:
            if not root:
                continue
            root_real = os.path.realpath(str(root))
            try:
                # commonpath() is separator aware: '/media-evil' does not match
                # the root '/media', which a str.startswith() test would allow.
                if os.path.commonpath([candidate, root_real]) == root_real:
                    return candidate
            except ValueError:
                # Not comparable (e.g. different drives on Windows).
                continue

        # Deliberately does not echo the requested path back to the caller.
        raise SuspiciousFileOperation(
            "storage_path is outside the allowed storage roots"
        )

    def _compute_digests(self, file_obj=None):
        """
        Compute and return ``(md5, sha256)`` for this file.

        Deliberately never touches ``self``: verify_checksum() depends on that
        so a recalculated digest can never overwrite the stored baseline.
        """
        opened_here = False

        if file_obj is None:
            if self.file:
                file_obj = self.file.open('rb')
                opened_here = True
            elif self.storage_path:
                file_obj = open(self._resolve_storage_path(), 'rb')
                opened_here = True
            else:
                raise ValueError("No file available for checksum calculation")
        else:
            # A caller-supplied handle may already be at EOF (e.g. an upload
            # Django has just written to storage).
            try:
                file_obj.seek(0)
            except (AttributeError, OSError, ValueError):
                pass

        md5_hash = hashlib.md5()
        sha256_hash = hashlib.sha256()

        try:
            # Read file in chunks to handle large files
            for chunk in iter(lambda: file_obj.read(8192), b''):
                md5_hash.update(chunk)
                sha256_hash.update(chunk)
        finally:
            # Only close handles we opened ourselves.
            if opened_here and hasattr(file_obj, 'close'):
                file_obj.close()

        return md5_hash.hexdigest(), sha256_hash.hexdigest()

    def calculate_checksums(self, file_obj=None):
        """
        Calculate and store MD5 and SHA-256 checksums for the file.
        Uses the uploaded file or reads from storage_path.

        This is the only method that writes the stored digests: it establishes
        (or deliberately re-establishes) the baseline, and is called explicitly
        by the API and admin actions. Verification must never call it.
        """
        self.checksum_md5, self.checksum_sha256 = self._compute_digests(file_obj)

    def _save_verification_state(self):
        """
        Persist only the verification bookkeeping fields.

        Restricting the write guarantees a verification can never overwrite the
        stored checksum baseline, whatever else happened to the in-memory
        instance beforehand.
        """
        if self.pk is None:
            self.save()
            return
        self.save(update_fields=[
            'status', 'last_verified_at', 'verification_error', 'updated_at'
        ])

    def verify_checksum(self, checksum_type='sha256'):
        """
        Verify file integrity against the *stored* checksum baseline.

        Returns True only when the bytes on disk still hash to the digest that
        was recorded earlier. The freshly computed digest is never written to
        the model, so a verification cannot destroy the evidence of corruption
        (and thereby report the same corrupt file as clean next time round).
        """
        from django.utils import timezone

        try:
            stored = (
                self.checksum_md5 if checksum_type == 'md5'
                else self.checksum_sha256
            )

            if not stored:
                # Nothing to compare against - a "match" here would be vacuous.
                self.last_verified_at = timezone.now()
                self.verification_error = (
                    f'No baseline {checksum_type.upper()} checksum recorded; '
                    'run calculate_checksums() to establish one.'
                )
                if self.status == 'verified':
                    # That claim is not backed by any baseline.
                    self.status = 'pending'
                self._save_verification_state()
                return False

            md5_digest, sha256_digest = self._compute_digests()
            current = md5_digest if checksum_type == 'md5' else sha256_digest
            verified = current == stored

            # Update status. self.checksum_* are left exactly as stored.
            self.last_verified_at = timezone.now()
            if verified:
                self.status = 'verified'
                self.verification_error = ''
            else:
                self.status = 'corrupted'
                self.verification_error = f'{checksum_type.upper()} checksum mismatch'

            self._save_verification_state()
            return verified

        except Exception as e:
            self.status = 'corrupted'
            self.verification_error = str(e)
            self.last_verified_at = timezone.now()
            self._save_verification_state()
            return False

    def get_absolute_url(self):
        """Returns URL for this file (useful for future detail views)"""
        return reverse('storagefile-detail', kwargs={'pk': self.pk})


class CostEstimate(models.Model):
    """
    Cost estimate for storing a data item with a specific provider.
    Tracks estimated and actual costs for storage and retrieval.
    """
    data_item = models.ForeignKey(
        DataItem,
        on_delete=models.CASCADE,
        related_name='cost_estimates',
        help_text="Data item this cost estimate is for"
    )
    provider = models.ForeignKey(
        StorageProvider,
        on_delete=models.CASCADE,
        related_name='cost_estimates',
        help_text="Storage provider"
    )

    # Size information
    estimated_size_gb = models.FloatField(
        validators=[MinValueValidator(0.0)],
        help_text="Estimated storage size in GB"
    )

    # Cost estimates
    monthly_storage_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Estimated monthly storage cost"
    )
    annual_storage_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Estimated annual storage cost"
    )
    estimated_retrieval_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Estimated one-time retrieval cost"
    )

    # Actual costs (if available)
    actual_monthly_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual monthly cost (from bills)"
    )
    actual_retrieval_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual retrieval cost (from bills)"
    )

    # Additional costs
    bandwidth_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Bandwidth/egress costs"
    )
    api_request_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="API request costs"
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this estimate is currently active"
    )
    notes = models.TextField(
        blank=True,
        help_text="Additional notes about this cost estimate"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['data_item', 'provider']
        indexes = [
            models.Index(fields=['data_item', 'provider']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.data_item.name} @ {self.provider.name}"

    def _costs_are_unset(self):
        """True when none of the three estimate fields has been supplied."""
        from decimal import Decimal, InvalidOperation

        for field_name in ('monthly_storage_cost', 'annual_storage_cost',
                           'estimated_retrieval_cost'):
            value = getattr(self, field_name)
            if value is None:
                continue
            default = self._meta.get_field(field_name).get_default()
            try:
                if Decimal(str(value)) != Decimal(str(default)):
                    return False
            except (InvalidOperation, TypeError, ValueError):
                return False
        return True

    def save(self, *args, **kwargs):
        """
        Auto-calculate costs only when creating an estimate that supplied none.

        Recalculating on every falsy cost silently overwrote operator-entered
        values and re-derived legitimately free ($0.00) local/NAS tiers on each
        save. Explicit recalculation goes through calculate_costs(), which the
        recalculate / bulk_recalculate API actions and the admin action call.
        """
        if self._state.adding and self._costs_are_unset():
            self.calculate_costs()
        super().save(*args, **kwargs)

    def calculate_costs(self):
        """Calculate estimated costs based on provider pricing."""
        size_gb = self.estimated_size_gb or self.data_item.size_estimate_gb or 0

        # Monthly storage cost
        self.monthly_storage_cost = round(
            self.provider.calculate_monthly_cost(size_gb), 2
        )

        # Annual storage cost
        self.annual_storage_cost = round(
            float(self.monthly_storage_cost) * 12, 2
        )

        # Retrieval cost
        self.estimated_retrieval_cost = round(
            self.provider.calculate_retrieval_cost(size_gb), 2
        )

    def get_total_first_year_cost(self):
        """Calculate total cost for first year (storage + retrieval)."""
        return float(self.annual_storage_cost) + float(self.estimated_retrieval_cost)

    def get_cost_comparison(self):
        """Get comparison between estimated and actual costs."""
        if not self.actual_monthly_cost:
            return None

        return {
            'estimated': float(self.monthly_storage_cost),
            'actual': float(self.actual_monthly_cost),
            'difference': float(self.actual_monthly_cost) - float(self.monthly_storage_cost),
            'percentage_diff': (
                (float(self.actual_monthly_cost) - float(self.monthly_storage_cost))
                / float(self.monthly_storage_cost) * 100
                if self.monthly_storage_cost > 0 else 0
            )
        }