import base64
from io import StringIO
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .cache import product_detail_cache_key
from .models import Product


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "product-api-tests",
        "TIMEOUT": 300,
    }
}


@override_settings(CACHES=TEST_CACHES)
class ProductAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="product-api-tester",
            password="test-password",
        )
        cls.staff_user = get_user_model().objects.create_user(
            username="inventory-manager",
            password="test-password",
            is_staff=True,
        )
        cls.phone = Product.objects.create(
            sku="PHONE-001",
            name="测试手机",
            price=Decimal("1999.00"),
            stock=10,
            sales=20,
        )
        cls.case = Product.objects.create(
            sku="CASE-001",
            name="测试手机壳",
            price=Decimal("29.90"),
            stock=0,
            sales=5,
        )
        cls.laptop = Product.objects.create(
            sku="LAPTOP-001",
            name="测试笔记本电脑",
            price=Decimal("5999.00"),
            stock=2,
            sales=3,
        )
        cls.cable = Product.objects.create(
            sku="CABLE-001",
            name="测试数据线",
            price=Decimal("49.00"),
            stock=100,
            sales=50,
        )

        for index in range(12):
            Product.objects.create(
                sku=f"EXTRA-{index:02d}",
                name=f"分页测试商品 {index:02d}",
                price=Decimal("100.00") + index,
                stock=1,
            )

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        credentials = base64.b64encode(
            b"product-api-tester:test-password"
        ).decode("ascii")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {credentials}")
        self.list_url = reverse("products:product-list")

    def test_unauthenticated_user_cannot_list_products(self):
        response = APIClient().get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_product_list_is_paginated(self):
        first_page = self.client.get(self.list_url)
        second_page = self.client.get(self.list_url, {"page": 2})

        self.assertEqual(first_page.status_code, status.HTTP_200_OK)
        self.assertEqual(first_page.data["count"], 16)
        self.assertEqual(len(first_page.data["results"]), 10)
        self.assertIsNotNone(first_page.data["next"])
        self.assertIsNone(first_page.data["previous"])

        self.assertEqual(second_page.status_code, status.HTTP_200_OK)
        self.assertEqual(len(second_page.data["results"]), 6)
        self.assertIsNone(second_page.data["next"])
        self.assertIsNotNone(second_page.data["previous"])

    def test_product_detail_returns_one_product(self):
        response = self.client.get(
            reverse("products:product-detail", args=[self.phone.id])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.phone.id)
        self.assertEqual(response.data["sku"], "PHONE-001")
        self.assertEqual(response.data["price"], "1999.00")
        self.assertEqual(response.data["stock"], 10)
        self.assertEqual(response["X-Cache"], "MISS")

    def test_product_detail_is_read_from_cache_after_first_request(self):
        detail_url = reverse(
            "products:product-detail",
            args=[self.phone.id],
        )

        first_response = self.client.get(detail_url)
        cached_data = cache.get(product_detail_cache_key(self.phone.id))

        Product.objects.filter(pk=self.phone.id).update(name="数据库中的新名称")
        second_response = self.client.get(detail_url)

        self.assertEqual(first_response["X-Cache"], "MISS")
        self.assertEqual(cached_data["name"], "测试手机")
        self.assertEqual(second_response["X-Cache"], "HIT")
        self.assertEqual(second_response.data["name"], "测试手机")

        cache.delete(product_detail_cache_key(self.phone.id))
        third_response = self.client.get(detail_url)

        self.assertEqual(third_response["X-Cache"], "MISS")
        self.assertEqual(third_response.data["name"], "数据库中的新名称")

    def test_missing_product_returns_404(self):
        response = self.client.get(
            reverse("products:product-detail", args=[999999])
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_matches_name_or_sku(self):
        name_response = self.client.get(self.list_url, {"search": "手机"})
        sku_response = self.client.get(self.list_url, {"search": "LAPTOP"})

        name_ids = {item["id"] for item in name_response.data["results"]}
        sku_ids = {item["id"] for item in sku_response.data["results"]}

        self.assertEqual(name_response.status_code, status.HTTP_200_OK)
        self.assertEqual(name_ids, {self.phone.id, self.case.id})
        self.assertEqual(sku_ids, {self.laptop.id})

    def test_in_stock_filter(self):
        response = self.client.get(self.list_url, {"in_stock": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.case.id)

    def test_price_filter_and_ordering(self):
        response = self.client.get(
            self.list_url,
            {
                "min_price": "20.00",
                "max_price": "50.00",
                "ordering": "price",
            },
        )
        sales_response = self.client.get(
            self.list_url,
            {"ordering": "-sales"},
        )

        result_ids = [item["id"] for item in response.data["results"]]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result_ids, [self.case.id, self.cable.id])
        self.assertEqual(sales_response.data["results"][0]["id"], self.cable.id)

    def test_invalid_filters_return_400(self):
        invalid_queries = (
            {"in_stock": "maybe"},
            {"min_price": "-1.00"},
            {"min_price": "100.00", "max_price": "10.00"},
            {"ordering": "stock"},
        )

        for query in invalid_queries:
            with self.subTest(query=query):
                response = self.client.get(self.list_url, query)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )

    def test_staff_user_can_stock_in_and_product_cache_is_deleted(self):
        self.client.force_authenticate(user=self.staff_user)
        cache_key = product_detail_cache_key(self.case.id)
        cache.set(cache_key, {"stock": 0, "sales": 5})

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                reverse("products:product-stock-in", args=[self.case.id]),
                {"quantity": 20},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["stock"], 20)
        self.assertEqual(response.data["sales"], 5)
        self.assertEqual(len(callbacks), 1)
        self.assertIsNone(cache.get(cache_key))

        self.case.refresh_from_db()
        self.assertEqual((self.case.stock, self.case.sales), (20, 5))

    def test_regular_user_cannot_stock_in(self):
        response = self.client.post(
            reverse("products:product-stock-in", args=[self.case.id]),
            {"quantity": 20},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stock, 0)

    def test_stock_in_requires_a_positive_integer(self):
        self.client.force_authenticate(user=self.staff_user)
        stock_in_url = reverse("products:product-stock-in", args=[self.case.id])

        for quantity in (0, -1, True, "1.5"):
            with self.subTest(quantity=quantity):
                response = self.client.post(
                    stock_in_url,
                    {"quantity": quantity},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.case.refresh_from_db()
        self.assertEqual(self.case.stock, 0)

    def test_stock_in_missing_product_returns_404(self):
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            reverse("products:product-stock-in", args=[999999]),
            {"quantity": 20},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_user_cannot_stock_in(self):
        response = APIClient().post(
            reverse("products:product-stock-in", args=[self.case.id]),
            {"quantity": 20},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class BenchmarkProductCommandTests(TestCase):
    def test_seed_is_repeatable_and_clear_only_removes_benchmark_products(self):
        normal_product = Product.objects.create(
            sku="NORMAL-PRODUCT",
            name="普通商品",
            price=Decimal("10.00"),
        )
        output = StringIO()

        call_command(
            "seed_benchmark_products",
            count=25,
            batch_size=7,
            stdout=output,
        )
        call_command(
            "seed_benchmark_products",
            count=25,
            batch_size=7,
            stdout=output,
        )

        self.assertEqual(
            Product.objects.filter(sku__startswith="BENCH-").count(),
            25,
        )
        self.assertTrue(Product.objects.filter(sku="BENCH-000025").exists())

        call_command("seed_benchmark_products", clear=True, stdout=output)

        self.assertFalse(Product.objects.filter(sku__startswith="BENCH-").exists())
        self.assertTrue(Product.objects.filter(pk=normal_product.pk).exists())
