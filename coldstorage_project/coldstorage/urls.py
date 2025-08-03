from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DataItemViewSet, CategoryViewSet

from .views import index, import_json

router = DefaultRouter()
router.register(r'items', DataItemViewSet)
router.register(r'categories', CategoryViewSet)

urlpatterns = [
    path('', index),
    path('import-json/', import_json, name='import_json'),
    path('api/', include(router.urls)),
]

urlpatterns += [
    path('dashboard/', dashboard),
]