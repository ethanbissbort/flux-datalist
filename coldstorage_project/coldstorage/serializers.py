"""
Serializers for the Cold Storage app.
Handles API representation and validation for Category and DataItem models.
"""
from typing import Dict, Any
from rest_framework import serializers
from .models import DataItem, Category, StorageFile


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
        """Returns the number of direct child categories."""
        return obj.children.count()

    def get_item_count(self, obj: Category) -> int:
        """Returns the number of data items in this category."""
        return obj.data_items.count()


class DataItemListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for list views.
    Uses nested category representation for reading.
    """
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_path = serializers.CharField(source='category.get_full_path', read_only=True)
    size_display = serializers.CharField(source='get_size_display', read_only=True)
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
    Includes all fields and computed properties.
    """
    category_detail = CategorySerializer(source='category', read_only=True)
    size_display = serializers.CharField(source='get_size_display', read_only=True)
    tags_list = serializers.ListField(source='get_tags_list', read_only=True)

    class Meta:
        model = DataItem
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class DataItemWriteSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and updating DataItems.
    Accepts category ID and handles validation.
    """
    class Meta:
        model = DataItem
        fields = [
            'name', 'category', 'subcategory', 'description', 'examples',
            'size_estimate_gb', 'tags', 'source_url', 'notes',
            'priority', 'status'
        ]

    def validate_size_estimate_gb(self, value: float) -> float:
        """Ensure size estimate is non-negative."""
        if value is not None and value < 0:
            raise serializers.ValidationError("Size estimate must be non-negative.")
        return value

    def validate_tags(self, value: str) -> str:
        """Clean and validate tags format."""
        if value:
            # Remove extra whitespace and normalize commas
            tags = [tag.strip() for tag in value.split(',') if tag.strip()]
            return ', '.join(tags)
        return value


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
        """Create StorageFile and automatically calculate checksums if file is provided."""
        file_obj = validated_data.get('file')
        storage_file = super().create(validated_data)

        if file_obj:
            # Set file size from uploaded file
            storage_file.file_size_bytes = file_obj.size
            storage_file.original_filename = file_obj.name

            # Calculate checksums
            try:
                storage_file.calculate_checksums(file_obj)
                storage_file.status = 'stored'
            except Exception as e:
                storage_file.verification_error = str(e)
                storage_file.status = 'corrupted'

            storage_file.save()

        return storage_file


class StorageFileUploadSerializer(serializers.ModelSerializer):
    """
    Simplified serializer for file uploads.
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
                f"File size exceeds maximum allowed size of 10GB."
            )

        return value
