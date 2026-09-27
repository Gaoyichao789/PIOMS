import base64
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .models import Product


class ProductAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="product-api-tester",
            password="test-password",
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
