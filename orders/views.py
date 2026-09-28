from django.db.models import Prefetch
from rest_framework import status
from rest_framework.generics import GenericAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .exceptions import (
    EmptyOrderError,
    InsufficientStockError,
    InvalidOrderItemError,
    InvalidOrderUserError,
    OrderNotCancellableError,
    OrderNotFoundError,
    ProductNotFoundError,
)
from .models import Order, OrderItem
from .serializers import OrderCreateSerializer, OrderSerializer
from .services import cancel_order, create_order


def _orders_for_user(user):
    return Order.objects.filter(user=user).prefetch_related(
        Prefetch(
            "items",
            queryset=OrderItem.objects.select_related("product"),
        )
    )


class OrderListCreateView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OrderCreateSerializer
        return OrderSerializer

    def get_queryset(self):
        return _orders_for_user(self.request.user)

    def get(self, request):
        page = self.paginate_queryset(self.get_queryset())
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = create_order(
                user=request.user,
                items=serializer.validated_data["items"],
            )
        except ProductNotFoundError as exc:
            return Response(
                {
                    "code": "product_not_found",
                    "detail": str(exc),
                    "product_ids": exc.product_ids,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InsufficientStockError as exc:
            return Response(
                {
                    "code": "insufficient_stock",
                    "detail": str(exc),
                    "product_id": exc.product_id,
                    "requested": exc.requested,
                    "available": exc.available,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except (EmptyOrderError, InvalidOrderItemError) as exc:
            return Response(
                {"code": "invalid_order", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InvalidOrderUserError as exc:
            return Response(
                {"code": "invalid_user", "detail": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        order = Order.objects.prefetch_related("items__product").get(pk=order.pk)
        return Response(
            OrderSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )


class OrderDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self):
        return _orders_for_user(self.request.user)


class OrderCancelView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def post(self, request, pk):
        try:
            order = cancel_order(user=request.user, order_id=pk)
        except OrderNotFoundError as exc:
            return Response(
                {"code": "order_not_found", "detail": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except OrderNotCancellableError as exc:
            return Response(
                {
                    "code": "order_not_cancellable",
                    "detail": str(exc),
                    "current_status": exc.current_status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        order = _orders_for_user(request.user).get(pk=order.pk)
        return Response(self.get_serializer(order).data)
