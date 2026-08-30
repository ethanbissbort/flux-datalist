"""
URL configuration for coldstorage_project project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
    path('admin/', admin.site.urls),
    # Django's default LOGIN_URL is /accounts/login/. The web views redirect
    # unauthenticated writers there, so the route has to exist — otherwise the
    # redirect lands on a 404 and the queued message is discarded with it.
    path('accounts/', include('django.contrib.auth.urls')),
    path('api-auth/', include('rest_framework.urls')),
    path('api/auth/token/', obtain_auth_token, name='api_token_auth'),
    path('', include('coldstorage.urls')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
