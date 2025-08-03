from rest_framework import viewsets
from .models import DataItem, Category
from .serializers import DataItemSerializer, CategorySerializer

from django.shortcuts import render, redirect
from .models import DataItem, Category

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
