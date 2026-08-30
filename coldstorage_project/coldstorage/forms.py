"""
Forms for the Cold Storage app.
Provides validation and cleaned data for web forms.
"""
from typing import Any, Dict
from django import forms
from .models import DataItem, Category


class DataItemForm(forms.ModelForm):
    """
    Form for creating and editing DataItem instances.

    The free-text ``tags`` input writes to the ``tag_set`` relation — the same
    place the API writes — rather than to the deprecated ``tags_old`` column.
    Otherwise the web UI and the API maintain two divergent sets of tags.
    """

    tags = forms.CharField(
        required=False,
        label='Tags',
        help_text='Comma-separated. Tags are created if they do not exist.',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Comma-separated tags'
        })
    )

    class Meta:
        model = DataItem
        fields = [
            'name', 'category', 'subcategory', 'description', 'examples',
            'size_estimate_gb', 'source_url', 'notes',
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate the tag input when editing an existing item.
        if self.instance.pk and not self.is_bound:
            self.fields['tags'].initial = self.instance.get_tags_display()

    def clean_tags(self) -> str:
        """Clean and normalize the comma-separated tag string."""
        tags = self.cleaned_data.get('tags', '')
        if tags:
            tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
            return ', '.join(tag_list)
        return tags

    def _save_m2m(self):
        """Apply the typed tags after the instance and its relations exist."""
        super()._save_m2m()
        self.instance.tag_set.clear()
        self.instance.add_tags_from_string(self.cleaned_data.get('tags', ''))

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
        """
        Validate that parent doesn't create a circular reference.

        Delegates to the model so the form, the serializer and the model all
        share one bounded implementation. The walk this used to do inline was
        unbounded and would itself hang on an already-cyclic row.
        """
        cleaned_data = super().clean()
        parent = cleaned_data.get('parent')

        if parent and self.instance.would_create_cycle(parent):
            raise forms.ValidationError(
                'Cannot set parent: would create a circular reference.'
            )

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
                Q(tag_set__name__icontains=search) |
                Q(tags_old__icontains=search) |
                Q(description__icontains=search)
            ).distinct()

        return queryset
