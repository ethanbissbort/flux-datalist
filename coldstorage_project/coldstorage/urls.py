"""
URL configuration for the coldstorage app.
Includes both REST API endpoints and traditional views.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DataItemViewSet, CategoryViewSet, StorageFileViewSet,
    TagViewSet, StorageProviderViewSet, CostEstimateViewSet,
    index, import_json, dashboard
)

# REST API router configuration
router = DefaultRouter()
router.register(r'items', DataItemViewSet, basename='dataitem')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'files', StorageFileViewSet, basename='storagefile')
router.register(r'tags', TagViewSet, basename='tag')
router.register(r'providers', StorageProviderViewSet, basename='storageprovider')
router.register(r'costs', CostEstimateViewSet, basename='costestimate')

# URL patterns
urlpatterns = [
    # Traditional views
    path('', index, name='index'),
    path('import-json/', import_json, name='import_json'),
    path('dashboard/', dashboard, name='dashboard'),

    # REST API endpoints
    path('api/', include(router.urls)),
]