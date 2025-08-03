from rest_framework import viewsets
from .models import DataItem, Category
from .serializers import DataItemSerializer, CategorySerializer

from django.shortcuts import render, redirect

from django.core.files.storage import default_storage

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

class DataItemViewSet(viewsets.ModelViewSet):
    queryset = DataItem.objects.all()
    serializer_class = DataItemSerializer



def index(request):
    if request.method == 'POST':
        DataItem.objects.create(
            name=request.POST['name'],
            category=Category.objects.get(id=request.POST['category']),
            size_estimate_gb=request.POST['size_estimate_gb'],
            tags=request.POST['tags'],
            description=request.POST['description']
        )
        return redirect('/')
    return render(request, 'index.html', {
        'items': DataItem.objects.all(),
        'categories': Category.objects.all()
    })

def import_json(request):
    if request.method == 'POST' and request.FILES['json_file']:
        file = request.FILES['json_file']
        data = json.load(file)

        for entry in data:
            category_name = entry.get('category', '')
            category, _ = Category.objects.get_or_create(name=category_name)

            DataItem.objects.create(
                name=entry.get('name', ''),
                category=category,
                description=entry.get('description', ''),
                examples=entry.get('examples', ''),
                size_estimate_gb=entry.get('size_estimate_gb') or None,
                tags=entry.get('tags', ''),
                source_url=entry.get('source_url', ''),
                notes=entry.get('notes', '')
            )
        return redirect('/')
    return redirect('/')

