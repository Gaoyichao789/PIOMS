class OrderServiceError(Exception):
    """Base exception for expected order business failures."""


class InvalidOrderUserError(OrderServiceError):
    def __init__(self):
        super().__init__("下单用户必须是已保存且已登录的用户")


class EmptyOrderError(OrderServiceError):
    def __init__(self):
        super().__init__("订单至少需要包含一件商品")


class InvalidOrderItemError(OrderServiceError):
    def __init__(self, index, reason):
        self.index = index
        self.reason = reason
        super().__init__(f"第 {index + 1} 条订单明细无效：{reason}")


class ProductNotFoundError(OrderServiceError):
    def __init__(self, product_ids):
        self.product_ids = tuple(sorted(product_ids))
        ids = ", ".join(str(product_id) for product_id in self.product_ids)
        super().__init__(f"商品不存在：{ids}")


class InsufficientStockError(OrderServiceError):
    def __init__(self, *, product_id, requested, available):
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"商品 {product_id} 库存不足：需要 {requested}，当前库存 {available}"
        )


class OrderNotFoundError(OrderServiceError):
    def __init__(self, order_id):
        self.order_id = order_id
        super().__init__(f"订单不存在：{order_id}")


class OrderNotCancellableError(OrderServiceError):
    def __init__(self, *, order_id, current_status):
        self.order_id = order_id
        self.current_status = current_status
        super().__init__(
            f"订单 {order_id} 当前状态为 {current_status}，不能取消"
        )
