from django.urls import path

from .views import OrderCreateView


app_name = "orders"

urlpatterns = [
    path("", OrderCreateView.as_view(), name="order-create"),
]
