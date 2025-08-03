from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DataItemViewSet, CategoryViewSet, index, import_json, dashboard

router = DefaultRouter()
router.register(r'items', DataItemViewSet)
router.register(r'categories', CategoryViewSet)

urlpatterns = [
    path('', index, name='index'),
    path('import-json/', import_json, name='import_json'),
    path('dashboard/', dashboard, name='dashboard'),
    path('api/', include(router.urls)),
]
