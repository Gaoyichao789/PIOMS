from django.db import models


class Product(models.Model):
    sku = models.CharField("SKU", max_length=64, unique=True)
    name = models.CharField("商品名称", max_length=200)
    price = models.DecimalField("价格", max_digits=12, decimal_places=2)
    stock = models.IntegerField("库存", default=0)
    sales = models.BigIntegerField("销量", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "商品"
        verbose_name_plural = "商品"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="product_price_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(stock__gte=0),
                name="product_stock_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(sales__gte=0),
                name="product_sales_gte_0",
            ),
        ]

    def __str__(self):
        return f"{self.sku} - {self.name}"
