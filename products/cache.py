PRODUCT_DETAIL_CACHE_KEY_PREFIX = "product:detail"


def product_detail_cache_key(product_id):
    return f"{PRODUCT_DETAIL_CACHE_KEY_PREFIX}:{product_id}"
