from django.contrib import admin
from .models import Category, DataItem

class DataItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'size_estimate_gb')
    search_fields = ('name', 'tags', 'description')
    list_filter = ('category',)

admin.site.register(Category)
admin.site.register(DataItem, DataItemAdmin)
