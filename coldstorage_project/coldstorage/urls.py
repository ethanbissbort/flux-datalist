from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DataItemViewSet, CategoryViewSet

from .views import index

router = DefaultRouter()
router.register(r'items', DataItemViewSet)
router.register(r'categories', CategoryViewSet)

urlpatterns = [
    path('', index),
    path('api/', include(router.urls)),
]
