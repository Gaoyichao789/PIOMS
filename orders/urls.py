from django.urls import path

from .views import OrderCancelView, OrderDetailView, OrderListCreateView


app_name = "orders"

urlpatterns = [
    path("", OrderListCreateView.as_view(), name="order-list-create"),
    path("<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("<int:pk>/cancel/", OrderCancelView.as_view(), name="order-cancel"),
]
