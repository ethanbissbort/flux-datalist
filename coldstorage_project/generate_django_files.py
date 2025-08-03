#!/usr/bin/env python3
"""
Django Core Files Generator for Cold Storage Project
This script creates all missing core Django files needed to run the application.
"""

import os
from pathlib import Path

def create_file(filepath, content):
    """Create a file with given content, creating directories if needed"""
    file_path = Path(filepath)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ Created: {filepath}")

def generate_django_files():
    """Generate all missing Django core files"""
    
    # Ensure we're in the right directory
    base_dir = Path.cwd()
    project_dir = base_dir / "coldstorage_project"
    
    print(f"🚀 Generating Django files in: {base_dir}")
    print("=" * 50)
    
    # 1. Create manage.py
    manage_py_content = '''#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coldstorage_project.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
'''
    create_file("coldstorage_project/manage.py", manage_py_content)
    
    # Make manage.py executable
    os.chmod("coldstorage_project/manage.py", 0o755)
    
    # 2. Create project __init__.py
    create_file("coldstorage_project/coldstorage_project/__init__.py", "")
    
    # 3. Create app __init__.py
    create_file("coldstorage_project/coldstorage/__init__.py", "")
    
    # 4. Create migrations __init__.py
    create_file("coldstorage_project/coldstorage/migrations/__init__.py", "")
    
    # 5. Create main urls.py
    main_urls_content = '''"""
URL configuration for coldstorage_project project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('coldstorage.urls')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
'''
    create_file("coldstorage_project/coldstorage_project/urls.py", main_urls_content)
    
    # 6. Create wsgi.py
    wsgi_content = '''"""
WSGI config for coldstorage_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coldstorage_project.settings')

application = get_wsgi_application()
'''
    create_file("coldstorage_project/coldstorage_project/wsgi.py", wsgi_content)
    
    # 7. Create asgi.py
    asgi_content = '''"""
ASGI config for coldstorage_project project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coldstorage_project.settings')

application = get_asgi_application()
'''
    create_file("coldstorage_project/coldstorage_project/asgi.py", asgi_content)
    
    # 8. Create apps.py for the coldstorage app
    apps_content = '''from django.apps import AppConfig


class ColdstorageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'coldstorage'
    verbose_name = 'Cold Storage Data Management'
'''
    create_file("coldstorage_project/coldstorage/apps.py", apps_content)
    
    # 9. Fix the coldstorage urls.py (remove dashboard function, keep only URLs)
    fixed_urls_content = '''from django.urls import path, include
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
'''
    create_file("coldstorage_project/coldstorage/urls.py", fixed_urls_content)
    
    # 10. Create a requirements.txt in the project root (for easier Docker setup)
    requirements_content = '''Django>=4.2,<5.0
djangorestframework>=3.14,<4.0
'''
    create_file("requirements.txt", requirements_content)
    
    # 11. Create improved docker-compose.yml
    docker_compose_content = '''version: "3.9"

services:
  web:
    build: 
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./coldstorage_project:/app
    environment:
      - DEBUG=True
      - DJANGO_SETTINGS_MODULE=coldstorage_project.settings
    command: >
      sh -c "python manage.py migrate &&
             python manage.py runserver 0.0.0.0:8000"
'''
    create_file("docker-compose.yml", docker_compose_content)
    
    # 12. Create improved Dockerfile
    dockerfile_content = '''FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY coldstorage_project/ /app/

# Create necessary directories
RUN mkdir -p /app/media /app/staticfiles

EXPOSE 8000

# The command will be overridden by docker-compose
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
'''
    create_file("Dockerfile", dockerfile_content)
    
    # 13. Create a setup script for initial data
    setup_script_content = '''#!/usr/bin/env python3
"""
Initial setup script for Cold Storage project
Run this after creating the Django files to set up the database and initial data
"""

import os
import sys
import django

# Add the project directory to Python path
sys.path.append('coldstorage_project')

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'coldstorage_project.settings')
django.setup()

from coldstorage.models import Category, DataItem

def create_initial_categories():
    """Create initial category structure"""
    categories = [
        {'name': 'Operating Systems', 'description': 'OS images and distributions'},
        {'name': 'Software', 'description': 'Applications and development tools'},
        {'name': 'Games', 'description': 'Video games and gaming content'},
        {'name': 'Media', 'description': 'Movies, TV shows, music, and entertainment'},
        {'name': 'Documents', 'description': 'Books, papers, and written content'},
        {'name': 'Data Archives', 'description': 'Datasets and research data'},
    ]
    
    for cat_data in categories:
        category, created = Category.objects.get_or_create(
            name=cat_data['name'],
            defaults={'description': cat_data['description']}
        )
        if created:
            print(f"✅ Created category: {category.name}")
        else:
            print(f"📋 Category exists: {category.name}")

def main():
    print("🚀 Setting up Cold Storage project...")
    print("=" * 50)
    
    # Create initial categories
    create_initial_categories()
    
    print("\\n✅ Setup complete!")
    print("\\nNext steps:")
    print("1. cd coldstorage_project")
    print("2. python manage.py runserver")
    print("3. Open http://127.0.0.1:8000 in your browser")

if __name__ == '__main__':
    main()
'''
    create_file("setup_project.py", setup_script_content)
    
    # Make setup script executable
    os.chmod("setup_project.py", 0o755)
    
    print("\n" + "=" * 50)
    print("🎉 ALL DJANGO CORE FILES GENERATED!")
    print("=" * 50)
    print("\n📋 Next Steps:")
    print("1. Run: python setup_project.py")
    print("2. cd coldstorage_project")
    print("3. python manage.py makemigrations")
    print("4. python manage.py migrate")
    print("5. python manage.py runserver")
    print("\n🐳 Or use Docker:")
    print("1. docker-compose up --build")
    print("\n✨ Your Django app should now start successfully!")

if __name__ == "__main__":
    generate_django_files()