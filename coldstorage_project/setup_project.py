#!/usr/bin/env python3
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
    
    print("\n✅ Setup complete!")
    print("\nNext steps:")
    print("1. cd coldstorage_project")
    print("2. python manage.py runserver")
    print("3. Open http://127.0.0.1:8000 in your browser")

if __name__ == '__main__':
    main()
