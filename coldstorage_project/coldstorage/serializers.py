from rest_framework import serializers
from .models import DataItem, Category

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'

class DataItemSerializer(serializers.ModelSerializer):
    category = CategorySerializer()
    
    class Meta:
        model = DataItem
        fields = '__all__'
