from django.db import transaction
from django.utils import timezone

from .cache import delete_product_detail_caches
from .models import Product


@transaction.atomic
def stock_in_product(*, product_id, quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("入库数量必须是正整数")

    product = Product.objects.select_for_update().get(pk=product_id)
    product.stock += quantity
    product.updated_at = timezone.now()
    product.save(update_fields=["stock", "updated_at"])

    transaction.on_commit(
        lambda: delete_product_detail_caches((product.pk,)),
        robust=True,
    )

    return product
