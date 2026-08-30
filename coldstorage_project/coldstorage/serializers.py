"""
Serializers for the Cold Storage app.
Handles API representation and validation for Category and DataItem models.
"""
from typing import Dict, Any
from rest_framework import serializers
from .models import (
    DataItem, Category, StorageFile, Tag,
    StorageProvider, CostEstimate
)


class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer for Category model.
    Includes full path and children count for better API representation.
    """
    full_path = serializers.CharField(source='get_full_path', read_only=True)
    children_count = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'description', 'parent',
            'full_path', 'children_count', 'item_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_children_count(self, obj: Category) -> int:
        """
        Returns the number of direct child categories.
        Prefers the queryset annotation added by CategoryViewSet to avoid a
        COUNT query per row.
        """
        annotated = getattr(obj, 'children_count_annotated', None)
        return annotated if annotated is not None else obj.children.count()

    def get_item_count(self, obj: Category) -> int:
        """
        Returns the number of data items in this category.
        Prefers the queryset annotation added by CategoryViewSet.
        """
        annotated = getattr(obj, 'item_count_annotated', None)
        return annotated if annotated is not None else obj.data_items.count()

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Reject a parent assignment that would create a cycle.

        CategoryForm performs this check for the web UI, but the API never
        touches that form. Without this a client can persist A -> B -> A, and
        every later read of the row spins forever in get_full_path().
        """
        parent = attrs.get('parent', serializers.empty)
        if parent is serializers.empty:
            return attrs

        instance = self.instance
        if instance is None:
            # On create the row has no pk yet, so it cannot be part of a cycle.
            return attrs

        if instance.would_create_cycle(parent):
            raise serializers.ValidationError({
                'parent': 'Cannot set parent: would create a circular reference.'
            })
        return attrs


class TagSerializer(serializers.ModelSerializer):
    """
    Serializer for Tag model.
    Includes usage count for statistics.
    """
    usage_count = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Tag
        fields = [
            'id', 'name', 'slug', 'description', 'color',
            'category', 'category_name', 'usage_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['slug', 'created_at', 'updated_at']

    def get_usage_count(self, obj: Tag) -> int:
        """
        Returns number of data items using this tag.
        Prefers the queryset annotation added by TagViewSet to avoid a COUNT
        query per row.
        """
        annotated = getattr(obj, 'usage_count_annotated', None)
        return annotated if annotated is not None else obj.get_usage_count()


class DataItemListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for list views.
    Uses nested category representation for reading.
    """
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_path = serializers.CharField(source='category.get_full_path', read_only=True)
    size_display = serializers.CharField(source='get_size_display', read_only=True)
    tags = serializers.CharField(source='get_tags_display', read_only=True)
    tags_list = serializers.ListField(source='get_tags_list', read_only=True)

    class Meta:
        model = DataItem
        fields = [
            'id', 'name', 'category', 'category_name', 'category_path',
            'subcategory', 'size_estimate_gb', 'size_display',
            'priority', 'status', 'tags', 'tags_list', 'updated_at'
        ]


class DataItemDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for single item views.
    Includes the nested category, the item's tags, and computed properties.
    """
    category_detail = CategorySerializer(source='category', read_only=True)
    size_display = serializers.CharField(source='get_size_display', read_only=True)
    tags = serializers.CharField(source='get_tags_display', read_only=True)
    tags_list = serializers.ListField(source='get_tags_list', read_only=True)
    tags_detail = TagSerializer(source='tag_set', many=True, read_only=True)

    class Meta:
        model = DataItem
        fields = [
            'id', 'name', 'category', 'category_detail', 'subcategory',
            'description', 'examples', 'size_estimate_gb', 'size_display',
            'tags', 'tags_list', 'tags_detail', 'source_url', 'notes',
            'priority', 'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class DataItemWriteSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and updating DataItems.

    Tags may be supplied either as a comma-separated string (``tags``, tags are
    created on demand by name) or as a list of existing Tag primary keys
    (``tag_ids``). Both replace the item's tag set outright; supplying both at
    once is rejected rather than silently picking a winner.
    """
    tags = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Comma-separated tag names. Tags are created if they do not exist."
    )
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Tag.objects.all(),
        write_only=True,
        required=False,
        help_text="Primary keys of existing tags."
    )

    class Meta:
        model = DataItem
        fields = [
            'name', 'category', 'subcategory', 'description', 'examples',
            'size_estimate_gb', 'tags', 'tag_ids', 'source_url', 'notes',
            'priority', 'status'
        ]

    def validate_size_estimate_gb(self, value: float) -> float:
        """Ensure size estimate is non-negative."""
        if value is not None and value < 0:
            raise serializers.ValidationError("Size estimate must be non-negative.")
        return value

    def validate_tags(self, value: str) -> str:
        """Clean and normalize the comma-separated tag string."""
        if value:
            tags = [tag.strip() for tag in value.split(',') if tag.strip()]
            return ', '.join(tags)
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Reject ambiguous input that sets tags two different ways at once."""
        if 'tags' in attrs and 'tag_ids' in attrs:
            raise serializers.ValidationError(
                "Provide either 'tags' or 'tag_ids', not both."
            )
        return attrs

    def _apply_tags(self, instance: DataItem, tags_string, tag_objects) -> None:
        """Replace the instance's tag set from whichever input was supplied."""
        if tag_objects is not None:
            instance.tag_set.set(tag_objects)
        elif tags_string is not None:
            instance.tag_set.clear()
            instance.add_tags_from_string(tags_string)

    def create(self, validated_data: Dict[str, Any]) -> DataItem:
        tags_string = validated_data.pop('tags', None)
        tag_objects = validated_data.pop('tag_ids', None)
        instance = super().create(validated_data)
        self._apply_tags(instance, tags_string, tag_objects)
        return instance

    def update(self, instance: DataItem, validated_data: Dict[str, Any]) -> DataItem:
        tags_string = validated_data.pop('tags', None)
        tag_objects = validated_data.pop('tag_ids', None)
        instance = super().update(instance, validated_data)
        self._apply_tags(instance, tags_string, tag_objects)
        return instance

    def to_representation(self, instance: DataItem) -> Dict[str, Any]:
        """Echo back the full read representation after a write."""
        return DataItemDetailSerializer(instance, context=self.context).data


# Alias for backwards compatibility
class DataItemSerializer(DataItemDetailSerializer):
    """
    Default DataItem serializer.
    Uses the detailed representation.
    """
    pass


class StorageFileSerializer(serializers.ModelSerializer):
    """
    Serializer for StorageFile model.
    Includes computed fields and file handling.
    """
    data_item_name = serializers.CharField(source='data_item.name', read_only=True)
    file_size_display = serializers.CharField(source='get_file_size_display', read_only=True)
    storage_location_display = serializers.CharField(
        source='get_storage_location_display',
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = StorageFile
        fields = [
            'id', 'data_item', 'data_item_name', 'file', 'file_path',
            'original_filename', 'file_size_bytes', 'file_size_display',
            'checksum_md5', 'checksum_sha256', 'storage_location',
            'storage_location_display', 'storage_path', 'status',
            'status_display', 'last_verified_at', 'verification_error',
            'mime_type', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'checksum_md5', 'checksum_sha256', 'last_verified_at',
            'verification_error', 'created_at', 'updated_at'
        ]

    def create(self, validated_data):
        """
        Create a StorageFile, deriving the required columns from the upload.

        The derived values must be set *before* the insert: original_filename
        and file_size_bytes are non-nullable, so assigning them afterwards is
        too late to prevent a NOT NULL violation.
        """
        file_obj = validated_data.get('file')
        if file_obj:
            validated_data.setdefault('original_filename', file_obj.name)
            validated_data.setdefault('file_size_bytes', file_obj.size)

        storage_file = super().create(validated_data)

        if file_obj:
            try:
                storage_file.calculate_checksums()
                storage_file.status = 'stored'
                storage_file.verification_error = ''
            except Exception as exc:  # noqa: BLE001 - recorded on the row
                storage_file.verification_error = str(exc)
                storage_file.status = 'corrupted'

            storage_file.save(update_fields=[
                'checksum_md5', 'checksum_sha256', 'status',
                'verification_error', 'updated_at',
            ])

        return storage_file


class StorageFileUploadSerializer(serializers.ModelSerializer):
    """
    Serializer for file uploads.

    ``original_filename`` and ``file_size_bytes`` are non-nullable on the model
    but are never supplied by the client, so they are derived from the uploaded
    file here. Without that the insert fails with a NOT NULL violation.
    """
    class Meta:
        model = StorageFile
        fields = [
            'data_item', 'file', 'storage_location', 'notes'
        ]

    def validate_file(self, value):
        """Validate uploaded file."""
        if not value:
            raise serializers.ValidationError("File is required for upload.")

        # Check file size (max 10GB for now)
        max_size = 10 * 1024 * 1024 * 1024  # 10GB
        if value.size > max_size:
            raise serializers.ValidationError(
                "File size exceeds maximum allowed size of 10GB."
            )

        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """A file is mandatory on this endpoint; it is what we measure and hash."""
        if not attrs.get('file'):
            raise serializers.ValidationError({'file': 'File is required for upload.'})
        return attrs

    def create(self, validated_data: Dict[str, Any]) -> StorageFile:
        """Populate the derived columns, then hash the stored file."""
        upload = validated_data['file']
        validated_data.setdefault('original_filename', upload.name)
        validated_data.setdefault('file_size_bytes', upload.size)

        storage_file = super().create(validated_data)

        try:
            storage_file.calculate_checksums()
            storage_file.status = 'stored'
            storage_file.verification_error = ''
        except Exception as exc:  # noqa: BLE001 - recorded on the row, not raised
            storage_file.status = 'corrupted'
            storage_file.verification_error = str(exc)

        storage_file.save(update_fields=[
            'checksum_md5', 'checksum_sha256', 'status',
            'verification_error', 'updated_at',
        ])
        return storage_file

    def to_representation(self, instance: StorageFile) -> Dict[str, Any]:
        """Return the full record so the client sees the derived fields."""
        return StorageFileSerializer(instance, context=self.context).data


class StorageProviderSerializer(serializers.ModelSerializer):
    """
    Serializer for StorageProvider model.
    Includes cost calculation methods.
    """
    provider_type_display = serializers.CharField(
        source='get_provider_type_display',
        read_only=True
    )
    estimate_count = serializers.SerializerMethodField()

    class Meta:
        model = StorageProvider
        fields = [
            'id', 'name', 'provider_type', 'provider_type_display',
            'cost_per_gb_monthly', 'retrieval_cost_per_gb',
            'api_cost_per_1000_requests', 'description', 'url',
            'is_active', 'estimate_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_estimate_count(self, obj: StorageProvider) -> int:
        """
        Returns number of cost estimates using this provider.
        Prefers the queryset annotation added by StorageProviderViewSet.
        """
        annotated = getattr(obj, 'estimate_count_annotated', None)
        return annotated if annotated is not None else obj.cost_estimates.count()


class CostEstimateSerializer(serializers.ModelSerializer):
    """
    Serializer for CostEstimate model.
    Includes calculated costs and comparisons.
    """
    data_item_name = serializers.CharField(source='data_item.name', read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    provider_type = serializers.CharField(source='provider.get_provider_type_display', read_only=True)
    total_first_year_cost = serializers.SerializerMethodField()
    cost_comparison = serializers.SerializerMethodField()

    class Meta:
        model = CostEstimate
        fields = [
            'id', 'data_item', 'data_item_name', 'provider', 'provider_name',
            'provider_type', 'estimated_size_gb', 'monthly_storage_cost',
            'annual_storage_cost', 'estimated_retrieval_cost',
            'actual_monthly_cost', 'actual_retrieval_cost',
            'bandwidth_cost', 'api_request_cost', 'total_first_year_cost',
            'cost_comparison', 'is_active', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'monthly_storage_cost', 'annual_storage_cost',
            'estimated_retrieval_cost', 'created_at', 'updated_at'
        ]

    def get_total_first_year_cost(self, obj: CostEstimate) -> float:
        """Calculate total first year cost."""
        return obj.get_total_first_year_cost()

    def get_cost_comparison(self, obj: CostEstimate):
        """Get comparison between estimated and actual costs."""
        return obj.get_cost_comparison()
