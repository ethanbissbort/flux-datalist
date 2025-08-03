import json
from rest_framework import viewsets
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.files.storage import default_storage
from django.db import models
from .models import DataItem, Category
from .serializers import DataItemSerializer, CategorySerializer


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class DataItemViewSet(viewsets.ModelViewSet):
    queryset = DataItem.objects.all()
    serializer_class = DataItemSerializer


def index(request):
    if request.method == 'POST':
        try:
            # Get or create category
            category_id = request.POST.get('category')
            category = Category.objects.get(id=category_id)
            
            # Create data item
            DataItem.objects.create(
                name=request.POST.get('name', ''),
                category=category,
                size_estimate_gb=request.POST.get('size_estimate_gb') or None,
                tags=request.POST.get('tags', ''),
                description=request.POST.get('description', ''),
                subcategory=request.POST.get('subcategory', ''),
                source_url=request.POST.get('source_url', ''),
                notes=request.POST.get('notes', ''),
                examples=request.POST.get('examples', '')
            )
            messages.success(request, 'Data item added successfully!')
        except Exception as e:
            messages.error(request, f'Error adding item: {str(e)}')
        
        return redirect('/')
    
    return render(request, 'index.html', {
        'items': DataItem.objects.all().order_by('-id'),
        'categories': Category.objects.all().order_by('name')
    })


def import_json(request):
    if request.method == 'POST' and request.FILES.get('json_file'):
        try:
            file = request.FILES['json_file']
            
            # Validate file type
            if not file.name.endswith('.json'):
                messages.error(request, 'Please upload a JSON file.')
                return redirect('/')
            
            # Parse JSON data
            try:
                file_content = file.read().decode('utf-8')
                data = json.loads(file_content)
            except json.JSONDecodeError as e:
                messages.error(request, f'Invalid JSON format: {str(e)}')
                return redirect('/')
            except UnicodeDecodeError:
                messages.error(request, 'File encoding not supported. Please use UTF-8.')
                return redirect('/')
            
            # Validate data structure
            if not isinstance(data, list):
                messages.error(request, 'JSON file must contain an array of objects.')
                return redirect('/')
            
            # Process each entry
            imported_count = 0
            errors = []
            
            for i, entry in enumerate(data):
                try:
                    if not isinstance(entry, dict):
                        errors.append(f'Entry {i+1}: Must be an object')
                        continue
                    
                    # Get or create category
                    category_name = entry.get('category', 'Uncategorized')
                    category, created = Category.objects.get_or_create(
                        name=category_name,
                        defaults={'description': f'Auto-created category for {category_name}'}
                    )
                    
                    # Validate required fields
                    name = entry.get('name', '').strip()
                    if not name:
                        errors.append(f'Entry {i+1}: Name is required')
                        continue
                    
                    # Parse size estimate
                    size_estimate = entry.get('size_estimate_gb')
                    if size_estimate is not None:
                        try:
                            size_estimate = float(size_estimate)
                        except (ValueError, TypeError):
                            size_estimate = None
                    
                    # Create data item
                    DataItem.objects.create(
                        name=name,
                        category=category,
                        description=entry.get('description', ''),
                        examples=entry.get('examples', ''),
                        size_estimate_gb=size_estimate,
                        tags=entry.get('tags', ''),
                        source_url=entry.get('source_url', ''),
                        notes=entry.get('notes', ''),
                        subcategory=entry.get('subcategory', '')
                    )
                    imported_count += 1
                    
                except Exception as e:
                    errors.append(f'Entry {i+1}: {str(e)}')
            
            # Report results
            if imported_count > 0:
                messages.success(request, f'Successfully imported {imported_count} items.')
            
            if errors:
                error_message = f'Encountered {len(errors)} errors:\n' + '\n'.join(errors[:5])
                if len(errors) > 5:
                    error_message += f'\n... and {len(errors) - 5} more errors.'
                messages.warning(request, error_message)
            
            if imported_count == 0 and errors:
                messages.error(request, 'No items were imported due to errors.')
                
        except Exception as e:
            messages.error(request, f'Unexpected error during import: {str(e)}')
    
    return redirect('/')


def dashboard(request):
    """Dashboard view with data visualization and filtering"""
    return render(request, 'dashboard.html', {
        'total_items': DataItem.objects.count(),
        'total_categories': Category.objects.count(),
        'total_size_gb': DataItem.objects.aggregate(
            total=models.Sum('size_estimate_gb')
        )['total'] or 0
    })