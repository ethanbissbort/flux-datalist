"""
Forms for the Cold Storage app.
Provides validation and cleaned data for web forms.
"""
from typing import Any, Dict
from django import forms
from .models import DataItem, Category


class DataItemForm(forms.ModelForm):
    """Form for creating and editing DataItem instances."""

    class Meta:
        model = DataItem
        fields = [
            'name', 'category', 'subcategory', 'description', 'examples',
            'size_estimate_gb', 'tags_old', 'source_url', 'notes',
            'priority', 'status'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter item name'
            }),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'subcategory': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional subcategory'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Detailed description'
            }),
            'examples': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Specific examples'
            }),
            'size_estimate_gb': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Size in GB',
                'step': '0.01',
                'min': '0'
            }),
            'tags_old': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Comma-separated tags'
            }),
            'source_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Additional notes'
            }),
            'priority': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_name(self) -> str:
        """Ensure name is not empty or just whitespace."""
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Name cannot be empty.')
        return name

    def clean_size_estimate_gb(self) -> float:
        """Ensure size estimate is non-negative."""
        size = self.cleaned_data.get('size_estimate_gb')
        if size is not None and size < 0:
            raise forms.ValidationError('Size estimate cannot be negative.')
        return size

    def clean_tags_old(self) -> str:
        """Clean and normalize tags."""
        tags = self.cleaned_data.get('tags_old', '')
        if tags:
            # Remove extra whitespace and normalize commas
            tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
            return ', '.join(tag_list)
        return tags


class CategoryForm(forms.ModelForm):
    """Form for creating and editing Category instances."""

    class Meta:
        model = Category
        fields = ['name', 'description', 'parent']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Category name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional description'
            }),
            'parent': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_name(self) -> str:
        """Ensure category name is not empty."""
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Category name cannot be empty.')
        return name

    def clean(self) -> Dict[str, Any]:
        """Validate that parent doesn't create a circular reference."""
        cleaned_data = super().clean()
        parent = cleaned_data.get('parent')

        if parent and self.instance.pk:
            # Check if setting this parent would create a cycle
            current = parent
            while current:
                if current.pk == self.instance.pk:
                    raise forms.ValidationError(
                        'Cannot set parent: would create a circular reference.'
                    )
                current = current.parent

        return cleaned_data


class JSONImportForm(forms.Form):
    """Form for uploading JSON files for import."""

    json_file = forms.FileField(
        label='JSON File',
        help_text='Upload a JSON file containing an array of data items.',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.json'
        })
    )

    def clean_json_file(self) -> Any:
        """Validate that the uploaded file is a JSON file."""
        file = self.cleaned_data.get('json_file')
        if file:
            if not file.name.endswith('.json'):
                raise forms.ValidationError('Please upload a JSON file.')

            # Check file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError('File size cannot exceed 10MB.')

        return file


class DataItemFilterForm(forms.Form):
    """Form for filtering data items in list views."""

    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        empty_label='All Categories',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + DataItem._meta.get_field('status').choices,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    priority = forms.ChoiceField(
        choices=[('', 'All Priorities')] + DataItem._meta.get_field('priority').choices,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by name, tags, or description'
        })
    )

    def filter_queryset(self, queryset):
        """Apply filters to a queryset based on form data."""
        if not self.is_valid():
            return queryset

        category = self.cleaned_data.get('category')
        if category:
            queryset = queryset.filter(category=category)

        status = self.cleaned_data.get('status')
        if status:
            queryset = queryset.filter(status=status)

        priority = self.cleaned_data.get('priority')
        if priority:
            queryset = queryset.filter(priority=priority)

        search = self.cleaned_data.get('search')
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(tags_old__icontains=search) |
                Q(description__icontains=search)
            )

        return queryset
