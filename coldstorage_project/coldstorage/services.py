"""
Service layer for Cold Storage app.
Contains business logic for data operations, separated from views.
"""
import json
from typing import Dict, List, Tuple, Any, Optional
from django.core.files.uploadedfile import UploadedFile
from .models import Category, DataItem


class ImportResult:
    """Container for import operation results."""

    def __init__(self):
        self.imported_count: int = 0
        self.errors: List[str] = []
        self.success: bool = False

    def add_error(self, error: str) -> None:
        """Add an error message to the result."""
        self.errors.append(error)

    def increment_imported(self) -> None:
        """Increment the count of successfully imported items."""
        self.imported_count += 1

    def finalize(self) -> None:
        """Mark the import as successful if any items were imported."""
        self.success = self.imported_count > 0

    def get_error_summary(self, max_errors: int = 5) -> str:
        """Get a summary of errors, limiting to max_errors."""
        if not self.errors:
            return ""

        error_message = f'Encountered {len(self.errors)} errors:\n'
        error_message += '\n'.join(self.errors[:max_errors])

        if len(self.errors) > max_errors:
            error_message += f'\n... and {len(self.errors) - max_errors} more errors.'

        return error_message


class JSONImportService:
    """Service for importing data from JSON files."""

    @staticmethod
    def validate_file(file: UploadedFile) -> Tuple[bool, Optional[str]]:
        """
        Validate uploaded file.
        Returns (is_valid, error_message).
        """
        if not file.name.endswith('.json'):
            return False, 'Please upload a JSON file.'
        return True, None

    @staticmethod
    def parse_json_file(file: UploadedFile) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """
        Parse JSON file content.
        Returns (data, error_message).
        """
        try:
            file_content = file.read().decode('utf-8')
            data = json.loads(file_content)
        except json.JSONDecodeError as e:
            return None, f'Invalid JSON format: {str(e)}'
        except UnicodeDecodeError:
            return None, 'File encoding not supported. Please use UTF-8.'

        if not isinstance(data, list):
            return None, 'JSON file must contain an array of objects.'

        return data, None

    @staticmethod
    def get_or_create_category(category_name: str) -> Category:
        """Get existing category or create a new one."""
        category, created = Category.objects.get_or_create(
            name=category_name,
            defaults={'description': f'Auto-created category for {category_name}'}
        )
        return category

    @staticmethod
    def parse_size_estimate(size_value: Any) -> Optional[float]:
        """Parse and validate size estimate value."""
        if size_value is None:
            return None

        try:
            return float(size_value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def create_data_item_from_entry(entry: Dict[str, Any], category: Category) -> DataItem:
        """Create a DataItem from a JSON entry."""
        return DataItem.objects.create(
            name=entry.get('name', '').strip(),
            category=category,
            description=entry.get('description', ''),
            examples=entry.get('examples', ''),
            size_estimate_gb=JSONImportService.parse_size_estimate(
                entry.get('size_estimate_gb')
            ),
            tags=entry.get('tags', ''),
            source_url=entry.get('source_url', ''),
            notes=entry.get('notes', ''),
            subcategory=entry.get('subcategory', ''),
            priority=entry.get('priority', 'medium'),
            status=entry.get('status', 'planned'),
        )

    @classmethod
    def import_from_json(cls, file: UploadedFile) -> ImportResult:
        """
        Import data items from a JSON file.
        Returns an ImportResult object with statistics and errors.
        """
        result = ImportResult()

        # Validate file
        is_valid, error = cls.validate_file(file)
        if not is_valid:
            result.add_error(error)
            return result

        # Parse JSON
        data, error = cls.parse_json_file(file)
        if error:
            result.add_error(error)
            return result

        # Process each entry
        for i, entry in enumerate(data):
            try:
                if not isinstance(entry, dict):
                    result.add_error(f'Entry {i+1}: Must be an object')
                    continue

                # Validate required fields
                name = entry.get('name', '').strip()
                if not name:
                    result.add_error(f'Entry {i+1}: Name is required')
                    continue

                # Get or create category
                category_name = entry.get('category', 'Uncategorized')
                category = cls.get_or_create_category(category_name)

                # Create data item
                cls.create_data_item_from_entry(entry, category)
                result.increment_imported()

            except Exception as e:
                result.add_error(f'Entry {i+1}: {str(e)}')

        result.finalize()
        return result


class DataItemService:
    """Service for managing DataItem operations."""

    @staticmethod
    def create_from_form_data(form_data: Dict[str, Any]) -> DataItem:
        """Create a DataItem from form data."""
        category = Category.objects.get(id=form_data['category_id'])

        return DataItem.objects.create(
            name=form_data.get('name', ''),
            category=category,
            size_estimate_gb=form_data.get('size_estimate_gb') or None,
            tags=form_data.get('tags', ''),
            description=form_data.get('description', ''),
            subcategory=form_data.get('subcategory', ''),
            source_url=form_data.get('source_url', ''),
            notes=form_data.get('notes', ''),
            examples=form_data.get('examples', ''),
            priority=form_data.get('priority', 'medium'),
            status=form_data.get('status', 'planned'),
        )

    @staticmethod
    def get_statistics() -> Dict[str, Any]:
        """Get overall statistics about data items."""
        from django.db.models import Sum, Count, Avg

        stats = DataItem.objects.aggregate(
            total_items=Count('id'),
            total_size=Sum('size_estimate_gb'),
            average_size=Avg('size_estimate_gb'),
        )

        # Get breakdown by status
        status_breakdown = DataItem.objects.values('status').annotate(
            count=Count('id')
        ).order_by('-count')

        # Get breakdown by priority
        priority_breakdown = DataItem.objects.values('priority').annotate(
            count=Count('id')
        ).order_by('-count')

        return {
            'total_items': stats['total_items'] or 0,
            'total_size_gb': stats['total_size'] or 0,
            'average_size_gb': stats['average_size'] or 0,
            'status_breakdown': list(status_breakdown),
            'priority_breakdown': list(priority_breakdown),
        }

    @staticmethod
    def get_category_statistics() -> List[Dict[str, Any]]:
        """Get statistics broken down by category."""
        from django.db.models import Sum, Count

        return list(
            Category.objects.annotate(
                item_count=Count('data_items'),
                total_size=Sum('data_items__size_estimate_gb')
            ).values(
                'id', 'name', 'item_count', 'total_size'
            ).order_by('-total_size')
        )
