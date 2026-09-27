from django.core.cache import cache


PRODUCT_DETAIL_CACHE_KEY_PREFIX = "product:detail"


def product_detail_cache_key(product_id):
    return f"{PRODUCT_DETAIL_CACHE_KEY_PREFIX}:{product_id}"


def delete_product_detail_caches(product_ids):
    cache_keys = [product_detail_cache_key(product_id) for product_id in product_ids]
    if cache_keys:
        cache.delete_many(cache_keys)
