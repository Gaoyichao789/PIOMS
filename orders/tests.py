from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from products.models import Product

from .exceptions import (
    EmptyOrderError,
    InsufficientStockError,
    InvalidOrderItemError,
    InvalidOrderUserError,
    ProductNotFoundError,
)
from .models import Order, OrderItem, OrderStatus
from .services import create_order


class CreateOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="order-tester",
            password="test-password",
        )
        cls.phone = Product.objects.create(
            sku="PHONE-TEST",
            name="测试手机",
            price=Decimal("1999.00"),
            stock=10,
        )
        cls.case = Product.objects.create(
            sku="CASE-TEST",
            name="测试手机壳",
            price=Decimal("29.90"),
            stock=5,
        )

    def test_create_order_creates_items_and_updates_inventory(self):
        order = create_order(
            user=self.user,
            items=[
                {"product_id": self.phone.id, "quantity": 2},
                {"product_id": self.case.id, "quantity": 1},
            ],
        )

        self.assertEqual(order.status, OrderStatus.PENDING)
        self.assertEqual(order.total_amount, Decimal("4027.90"))
        self.assertTrue(order.order_no.startswith("ORD"))
        self.assertEqual(len(order.order_no), 31)
        self.assertEqual(order.items.count(), 2)

        phone_item = order.items.get(product=self.phone)
        self.assertEqual(phone_item.quantity, 2)
        self.assertEqual(phone_item.unit_price, Decimal("1999.00"))
        self.assertEqual(phone_item.subtotal, Decimal("3998.00"))

        self.phone.refresh_from_db()
        self.case.refresh_from_db()
        self.assertEqual((self.phone.stock, self.phone.sales), (8, 2))
        self.assertEqual((self.case.stock, self.case.sales), (4, 1))

    def test_duplicate_products_are_merged_into_one_item(self):
        order = create_order(
            user=self.user,
            items=[
                {"product_id": self.phone.id, "quantity": 1},
                {"product_id": self.phone.id, "quantity": 2},
            ],
        )

        item = order.items.get()
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.subtotal, Decimal("5997.00"))

        self.phone.refresh_from_db()
        self.assertEqual((self.phone.stock, self.phone.sales), (7, 3))

    def test_order_item_keeps_price_snapshot(self):
        order = create_order(
            user=self.user,
            items=[{"product_id": self.case.id, "quantity": 1}],
        )

        self.case.price = Decimal("39.90")
        self.case.save(update_fields=["price"])

        item = order.items.get()
        self.assertEqual(item.unit_price, Decimal("29.90"))
        self.assertEqual(item.subtotal, Decimal("29.90"))
        self.assertEqual(order.total_amount, Decimal("29.90"))

    def test_insufficient_stock_does_not_create_or_change_anything(self):
        with self.assertRaises(InsufficientStockError) as context:
            create_order(
                user=self.user,
                items=[
                    {"product_id": self.phone.id, "quantity": 1},
                    {"product_id": self.case.id, "quantity": 6},
                ],
            )

        self.assertEqual(context.exception.product_id, self.case.id)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)

        self.phone.refresh_from_db()
        self.case.refresh_from_db()
        self.assertEqual((self.phone.stock, self.phone.sales), (10, 0))
        self.assertEqual((self.case.stock, self.case.sales), (5, 0))

    def test_missing_product_does_not_create_order(self):
        missing_id = max(self.phone.id, self.case.id) + 1000

        with self.assertRaises(ProductNotFoundError) as context:
            create_order(
                user=self.user,
                items=[{"product_id": missing_id, "quantity": 1}],
            )

        self.assertEqual(context.exception.product_ids, (missing_id,))
        self.assertEqual(Order.objects.count(), 0)

    def test_empty_order_is_rejected(self):
        with self.assertRaises(EmptyOrderError):
            create_order(user=self.user, items=[])

        self.assertEqual(Order.objects.count(), 0)

    def test_invalid_item_values_are_rejected(self):
        invalid_items = [
            [{"product_id": 0, "quantity": 1}],
            [{"product_id": True, "quantity": 1}],
            [{"product_id": self.phone.id, "quantity": 0}],
            [{"product_id": self.phone.id, "quantity": True}],
            ["not-a-mapping"],
        ]

        for items in invalid_items:
            with self.subTest(items=items):
                with self.assertRaises(InvalidOrderItemError):
                    create_order(user=self.user, items=items)

        self.assertEqual(Order.objects.count(), 0)

    def test_anonymous_user_is_rejected(self):
        with self.assertRaises(InvalidOrderUserError):
            create_order(
                user=AnonymousUser(),
                items=[{"product_id": self.phone.id, "quantity": 1}],
            )

        self.assertEqual(Order.objects.count(), 0)
