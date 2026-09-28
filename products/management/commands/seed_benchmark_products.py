import time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models.deletion import ProtectedError

from products.models import Product


BENCHMARK_SKU_PREFIX = "BENCH-"
PRODUCT_NAMES = (
    "手机",
    "手机壳",
    "笔记本电脑",
    "数据线",
    "充电器",
)


class Command(BaseCommand):
    help = "生成或清理用于查询性能实验的 BENCH- 商品数据。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=50_000,
            help="希望存在的 BENCH- 商品编号数量，默认 50000。",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1_000,
            help="每批写入数量，默认 1000。",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="删除所有 SKU 以 BENCH- 开头且未被订单引用的商品。",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self._clear_benchmark_products()
            return

        count = options["count"]
        batch_size = options["batch_size"]
        if count <= 0:
            raise CommandError("--count 必须是正整数。")
        if batch_size <= 0:
            raise CommandError("--batch-size 必须是正整数。")

        started_at = time.perf_counter()
        before_count = Product.objects.filter(
            sku__startswith=BENCHMARK_SKU_PREFIX
        ).count()
        existing_skus = set(
            Product.objects.filter(sku__startswith=BENCHMARK_SKU_PREFIX)
            .values_list("sku", flat=True)
        )

        for start in range(1, count + 1, batch_size):
            stop = min(start + batch_size, count + 1)
            products = [
                self._build_product(index)
                for index in range(start, stop)
                if self._sku(index) not in existing_skus
            ]
            if products:
                Product.objects.bulk_create(
                    products,
                    batch_size=batch_size,
                    ignore_conflicts=True,
                )

        after_count = Product.objects.filter(
            sku__startswith=BENCHMARK_SKU_PREFIX
        ).count()
        elapsed = time.perf_counter() - started_at
        self.stdout.write(
            self.style.SUCCESS(
                f"BENCH- 商品现有 {after_count} 条，本次新增 "
                f"{after_count - before_count} 条，耗时 {elapsed:.2f} 秒。"
            )
        )

    def _build_product(self, index):
        name = PRODUCT_NAMES[(index - 1) % len(PRODUCT_NAMES)]
        price = Decimal(100 + index % 500_000) / Decimal("100")
        return Product(
            sku=self._sku(index),
            name=f"性能测试{name} {index:06d}",
            price=price,
            stock=(index * 17) % 201,
            sales=(index * 29) % 10_001,
        )

    def _sku(self, index):
        return f"{BENCHMARK_SKU_PREFIX}{index:06d}"

    def _clear_benchmark_products(self):
        queryset = Product.objects.filter(sku__startswith=BENCHMARK_SKU_PREFIX)
        count = queryset.count()
        try:
            queryset.delete()
        except ProtectedError as exc:
            raise CommandError(
                "部分 BENCH- 商品已被订单引用，无法清理；请勿使用性能测试商品下单。"
            ) from exc

        self.stdout.write(self.style.SUCCESS(f"已删除 {count} 条 BENCH- 商品。"))
