from decimal import Decimal

from rest_framework import serializers

from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = (
            "id",
            "sku",
            "name",
            "price",
            "stock",
            "sales",
        )
        read_only_fields = fields


class ProductStockInSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class ProductListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=200,
    )
    in_stock = serializers.BooleanField(required=False)
    min_price = serializers.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
    )
    max_price = serializers.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
    )
    ordering = serializers.ChoiceField(
        required=False,
        default="-created_at",
        choices=(
            "price",
            "-price",
            "sales",
            "-sales",
            "name",
            "-name",
            "created_at",
            "-created_at",
        ),
    )

    def validate(self, attrs):
        min_price = attrs.get("min_price")
        max_price = attrs.get("max_price")

        if (
            min_price is not None
            and max_price is not None
            and min_price > max_price
        ):
            raise serializers.ValidationError(
                {"max_price": "最高价格不能低于最低价格。"}
            )

        return attrs
