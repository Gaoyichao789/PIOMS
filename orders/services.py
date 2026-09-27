import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from products.cache import delete_product_detail_caches
from products.models import Product

from .exceptions import (
    EmptyOrderError,
    InsufficientStockError,
    InvalidOrderItemError,
    InvalidOrderUserError,
    ProductNotFoundError,
)
from .models import Order, OrderItem, OrderStatus


def _generate_order_no():
    date_part = timezone.localdate().strftime("%Y%m%d")
    random_part = uuid.uuid4().hex[:20].upper()
    return f"ORD{date_part}{random_part}"


def _normalize_items(items: Iterable[Mapping[str, Any]]):
    quantities_by_product_id = {}

    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise InvalidOrderItemError(index, "明细必须是键值对象")

        product_id = item.get("product_id")
        quantity = item.get("quantity")

        if (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id <= 0
        ):
            raise InvalidOrderItemError(index, "product_id 必须是正整数")

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise InvalidOrderItemError(index, "quantity 必须是正整数")

        quantities_by_product_id[product_id] = (
            quantities_by_product_id.get(product_id, 0) + quantity
        )

    if not quantities_by_product_id:
        raise EmptyOrderError()

    return quantities_by_product_id


@transaction.atomic
def create_order(*, user, items):
    if (
        not getattr(user, "is_authenticated", False)
        or getattr(user, "pk", None) is None
    ):
        raise InvalidOrderUserError()

    quantities_by_product_id = _normalize_items(items)
    product_ids = sorted(quantities_by_product_id)

    products = list(
        Product.objects.select_for_update()
        .filter(pk__in=product_ids)
        .order_by("pk")
    )
    products_by_id = {product.pk: product for product in products}

    missing_product_ids = set(product_ids) - products_by_id.keys()
    if missing_product_ids:
        raise ProductNotFoundError(missing_product_ids)

    item_values = []
    total_amount = Decimal("0.00")

    for product_id in product_ids:
        product = products_by_id[product_id]
        quantity = quantities_by_product_id[product_id]

        if product.stock < quantity:
            raise InsufficientStockError(
                product_id=product_id,
                requested=quantity,
                available=product.stock,
            )

        subtotal = product.price * quantity
        total_amount += subtotal
        item_values.append((product, quantity, product.price, subtotal))

    order = Order.objects.create(
        order_no=_generate_order_no(),
        user=user,
        status=OrderStatus.PENDING,
        total_amount=total_amount,
    )

    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
                subtotal=subtotal,
            )
            for product, quantity, unit_price, subtotal in item_values
        ]
    )

    updated_at = timezone.now()
    for product, quantity, _, _ in item_values:
        product.stock -= quantity
        product.sales += quantity
        product.updated_at = updated_at

    Product.objects.bulk_update(products, ["stock", "sales", "updated_at"])

    cache_product_ids = tuple(product_ids)
    transaction.on_commit(
        lambda: delete_product_detail_caches(cache_product_ids),
        robust=True,
    )

    return order
