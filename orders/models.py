from django.conf import settings
from django.db import models

from products.models import Product


class OrderStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    PAID = "paid", "已支付"
    CANCELLED = "cancelled", "已取消"


class Order(models.Model):
    order_no = models.CharField("订单号", max_length=32, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="用户",
    )
    status = models.CharField(
        "状态",
        max_length=16,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )
    total_amount = models.DecimalField("订单总额", max_digits=14, decimal_places=2)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "订单"
        verbose_name_plural = "订单"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="order_user_created_idx",
            ),
            models.Index(
                fields=["status", "-created_at"],
                name="order_status_created_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="order_total_amount_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=OrderStatus.values),
                name="order_status_valid",
            ),
        ]

    def __str__(self):
        return self.order_no


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="订单",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="商品",
    )
    quantity = models.IntegerField("数量")
    unit_price = models.DecimalField("下单单价", max_digits=12, decimal_places=2)
    subtotal = models.DecimalField("明细小计", max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "订单明细"
        verbose_name_plural = "订单明细"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "product"],
                name="order_item_order_product_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="order_item_quantity_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="order_item_unit_price_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0),
                name="order_item_subtotal_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    subtotal=models.F("unit_price") * models.F("quantity")
                ),
                name="order_item_subtotal_matches_price_quantity",
            ),
        ]

    def __str__(self):
        return f"{self.order.order_no} - {self.product.sku} × {self.quantity}"
