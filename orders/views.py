from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .exceptions import (
    EmptyOrderError,
    InsufficientStockError,
    InvalidOrderItemError,
    InvalidOrderUserError,
    ProductNotFoundError,
)
from .models import Order
from .serializers import OrderCreateSerializer, OrderSerializer
from .services import create_order


class OrderCreateView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderCreateSerializer

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
