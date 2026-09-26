from django.contrib import admin

from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "sku",
        "name",
        "price",
        "stock",
        "sales",
        "updated_at",
    )
    search_fields = ("sku", "name")
    readonly_fields = ("sales", "created_at", "updated_at")
