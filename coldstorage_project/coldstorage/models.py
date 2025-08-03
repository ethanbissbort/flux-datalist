from django.db import models

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)

    def __str__(self):
        return self.name

class DataItem(models.Model):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    description = models.TextField(blank=True)
    examples = models.TextField(blank=True)
    size_estimate_gb = models.FloatField(null=True, blank=True)
    tags = models.CharField(max_length=250, blank=True)  # Comma-separated tags
    source_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name
