import base64
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from products.cache import product_detail_cache_key
from products.models import Product

from .exceptions import (
    EmptyOrderError,
    InsufficientStockError,
    InvalidOrderItemError,
    InvalidOrderUserError,
    OrderNotCancellableError,
    OrderNotFoundError,
    ProductNotFoundError,
)
from .models import Order, OrderItem, OrderStatus
from .services import cancel_order, create_order


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "orders-tests",
    }
}


@override_settings(CACHES=TEST_CACHES)
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

    def setUp(self):
        cache.clear()

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

    def test_successful_order_deletes_related_product_caches_after_commit(self):
        phone_cache_key = product_detail_cache_key(self.phone.id)
        case_cache_key = product_detail_cache_key(self.case.id)
        unrelated_cache_key = product_detail_cache_key(999999)
        cache.set(phone_cache_key, {"stock": 10})
        cache.set(case_cache_key, {"stock": 5})
        cache.set(unrelated_cache_key, {"stock": 99})

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            create_order(
                user=self.user,
                items=[
                    {"product_id": self.phone.id, "quantity": 1},
                    {"product_id": self.case.id, "quantity": 1},
                ],
            )

        self.assertEqual(len(callbacks), 1)
        self.assertIsNone(cache.get(phone_cache_key))
        self.assertIsNone(cache.get(case_cache_key))
        self.assertEqual(cache.get(unrelated_cache_key), {"stock": 99})

    def test_failed_order_keeps_product_cache(self):
        phone_cache_key = product_detail_cache_key(self.phone.id)
        cached_phone = {"stock": 10}
        cache.set(phone_cache_key, cached_phone)

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(InsufficientStockError):
                create_order(
                    user=self.user,
                    items=[
                        {"product_id": self.phone.id, "quantity": 1},
                        {"product_id": self.case.id, "quantity": 6},
                    ],
                )

        self.assertEqual(len(callbacks), 0)
        self.assertEqual(cache.get(phone_cache_key), cached_phone)

    def test_cancel_order_restores_inventory_and_deletes_cache_after_commit(self):
        order = create_order(
            user=self.user,
            items=[{"product_id": self.phone.id, "quantity": 2}],
        )
        cache_key = product_detail_cache_key(self.phone.id)
        cache.set(cache_key, {"stock": 8, "sales": 2})

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            cancelled_order = cancel_order(user=self.user, order_id=order.id)

        cancelled_order.refresh_from_db()
        self.phone.refresh_from_db()
        self.assertEqual(cancelled_order.status, OrderStatus.CANCELLED)
        self.assertEqual((self.phone.stock, self.phone.sales), (10, 0))
        self.assertEqual(len(callbacks), 1)
        self.assertIsNone(cache.get(cache_key))

    def test_non_pending_order_cannot_be_cancelled(self):
        order = Order.objects.create(
            order_no="PAID-ORDER",
            user=self.user,
            status=OrderStatus.PAID,
            total_amount=Decimal("0.00"),
        )

        with self.assertRaises(OrderNotCancellableError) as context:
            cancel_order(user=self.user, order_id=order.id)

        self.assertEqual(context.exception.current_status, OrderStatus.PAID)

    def test_user_cannot_cancel_another_users_order(self):
        other_user = get_user_model().objects.create_user(username="other-user")
        order = Order.objects.create(
            order_no="OTHER-USERS-ORDER",
            user=self.user,
            status=OrderStatus.PENDING,
            total_amount=Decimal("0.00"),
        )

        with self.assertRaises(OrderNotFoundError):
            cancel_order(user=other_user, order_id=order.id)


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
        self.url = reverse("orders:order-list-create")

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


@override_settings(CACHES=TEST_CACHES)
class OrderReadCancelAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(
            username="order-reader",
            password="test-password",
        )
        cls.other_user = user_model.objects.create_user(
            username="another-order-reader",
            password="test-password",
        )
        cls.product = Product.objects.create(
            sku="ORDER-READ-PRODUCT",
            name="订单查询测试商品",
            price=Decimal("100.00"),
            stock=20,
            sales=12,
        )

        cls.orders = []
        for index in range(12):
            order = Order.objects.create(
                order_no=f"READ-ORDER-{index:02d}",
                user=cls.user,
                status=OrderStatus.PENDING,
                total_amount=Decimal("100.00"),
            )
            OrderItem.objects.create(
                order=order,
                product=cls.product,
                quantity=1,
                unit_price=Decimal("100.00"),
                subtotal=Decimal("100.00"),
            )
            cls.orders.append(order)

        cls.other_order = Order.objects.create(
            order_no="ANOTHER-USERS-ORDER",
            user=cls.other_user,
            status=OrderStatus.PENDING,
            total_amount=Decimal("100.00"),
        )
        OrderItem.objects.create(
            order=cls.other_order,
            product=cls.product,
            quantity=1,
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
        )

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.list_url = reverse("orders:order-list-create")

    def test_order_list_is_paginated_and_only_contains_current_users_orders(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 12)
        self.assertEqual(len(response.data["results"]), 10)
        returned_ids = {order["id"] for order in response.data["results"]}
        self.assertNotIn(self.other_order.id, returned_ids)

    def test_order_list_uses_fixed_number_of_queries(self):
        with self.assertNumQueries(3):
            response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 10)

    def test_order_detail_contains_items(self):
        order = self.orders[0]
        response = self.client.get(
            reverse("orders:order-detail", args=[order.id])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], order.id)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(
            response.data["items"][0]["product_name"],
            self.product.name,
        )

    def test_another_users_order_detail_returns_404(self):
        response = self.client.get(
            reverse("orders:order-detail", args=[self.other_order.id])
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_order_restores_inventory_and_cannot_be_repeated(self):
        order = self.orders[0]
        cache_key = product_detail_cache_key(self.product.id)
        cache.set(cache_key, {"stock": 20, "sales": 12})
        cancel_url = reverse("orders:order-cancel", args=[order.id])

        with self.captureOnCommitCallbacks(execute=True):
            first_response = self.client.post(cancel_url)
        second_response = self.client.post(cancel_url)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response.data["status"], OrderStatus.CANCELLED)
        self.assertIsNone(cache.get(cache_key))

        self.product.refresh_from_db()
        self.assertEqual((self.product.stock, self.product.sales), (21, 11))

        self.assertEqual(second_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second_response.data["code"], "order_not_cancellable")
        self.product.refresh_from_db()
        self.assertEqual((self.product.stock, self.product.sales), (21, 11))

    def test_cannot_cancel_another_users_order(self):
        response = self.client.post(
            reverse("orders:order-cancel", args=[self.other_order.id])
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "order_not_found")

    def test_unauthenticated_user_cannot_list_orders(self):
        response = APIClient().get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(CACHES=TEST_CACHES)
class OrderConcurrencyTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.first_user = user_model.objects.create_user(username="buyer-one")
        self.second_user = user_model.objects.create_user(username="buyer-two")
        self.product = Product.objects.create(
            sku="LAST-ONE",
            name="最后一件并发测试商品",
            price=Decimal("100.00"),
            stock=1,
        )
        self.start_barrier = threading.Barrier(2)

    def _try_to_buy_last_product(self, user_id):
        close_old_connections()
        try:
            user = get_user_model().objects.get(pk=user_id)
            self.start_barrier.wait(timeout=5)

            try:
                order = create_order(
                    user=user,
                    items=[{"product_id": self.product.id, "quantity": 1}],
                )
            except InsufficientStockError:
                return "insufficient_stock", None

            return "created", order.id
        finally:
            close_old_connections()

    def test_two_users_competing_for_last_product_create_only_one_order(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    self._try_to_buy_last_product,
                    (self.first_user.id, self.second_user.id),
                )
            )

        outcomes = [outcome for outcome, _ in results]
        self.assertCountEqual(outcomes, ["created", "insufficient_stock"])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

        self.product.refresh_from_db()
        self.assertEqual((self.product.stock, self.product.sales), (0, 1))
