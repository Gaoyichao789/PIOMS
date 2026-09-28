from django.urls import path

from .views import ProductDetailView, ProductListView, ProductStockInView


app_name = "products"

urlpatterns = [
    path("", ProductListView.as_view(), name="product-list"),
    path("<int:pk>/", ProductDetailView.as_view(), name="product-detail"),
    path("<int:pk>/stock-in/", ProductStockInView.as_view(), name="product-stock-in"),
]
