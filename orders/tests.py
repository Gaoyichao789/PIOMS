import base64
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

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


class OrderCreateAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="api-order-tester",
            password="test-password",
        )
        cls.product = Product.objects.create(
            sku="API-PHONE-TEST",
            name="API 测试手机",
            price=Decimal("999.00"),
            stock=5,
        )

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("orders:order-create")

    def test_unauthenticated_user_cannot_create_order(self):
        response = self.client.post(
            self.url,
            {
                "items": [
                    {"product_id": self.product.id, "quantity": 1},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Order.objects.count(), 0)

    def test_basic_authenticated_user_can_create_order(self):
        credentials = base64.b64encode(
            b"api-order-tester:test-password"
        ).decode("ascii")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {credentials}")

        response = self.client.post(
            self.url,
            {
                "items": [
                    {"product_id": self.product.id, "quantity": 2},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], OrderStatus.PENDING)
        self.assertEqual(response.data["total_amount"], "1998.00")
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["product_id"], self.product.id)
        self.assertEqual(response.data["items"][0]["product_name"], self.product.name)
        self.assertEqual(response.data["items"][0]["quantity"], 2)

        order = Order.objects.get(pk=response.data["id"])
        self.assertEqual(order.user, self.user)
        self.product.refresh_from_db()
        self.assertEqual((self.product.stock, self.product.sales), (3, 2))

    def test_invalid_quantity_returns_400(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.url,
            {
                "items": [
                    {"product_id": self.product.id, "quantity": 0},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("quantity", response.data["items"][0])
        self.assertEqual(Order.objects.count(), 0)

    def test_missing_product_returns_400(self):
        self.client.force_authenticate(user=self.user)
        missing_id = self.product.id + 1000

        response = self.client.post(
            self.url,
            {
                "items": [
                    {"product_id": missing_id, "quantity": 1},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "product_not_found")
        self.assertEqual(list(response.data["product_ids"]), [missing_id])
        self.assertEqual(Order.objects.count(), 0)

    def test_insufficient_stock_returns_409_without_changes(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.url,
            {
                "items": [
                    {"product_id": self.product.id, "quantity": 6},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "insufficient_stock")
        self.assertEqual(response.data["product_id"], self.product.id)
        self.assertEqual(response.data["requested"], 6)
        self.assertEqual(response.data["available"], 5)
        self.assertEqual(Order.objects.count(), 0)

        self.product.refresh_from_db()
        self.assertEqual((self.product.stock, self.product.sales), (5, 0))
        self.assertEqual(OrderItem.objects.count(), 0)
