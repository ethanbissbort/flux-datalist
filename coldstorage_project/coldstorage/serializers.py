"""
Serializers for the Cold Storage app.
Handles API representation and validation for Category and DataItem models.
"""
from typing import Dict, Any
from rest_framework import serializers
from .models import DataItem, Category


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
