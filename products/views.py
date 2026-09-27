from django.core.cache import cache
from django.db.models import Q
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from .cache import product_detail_cache_key
from .models import Product
from .serializers import ProductListQuerySerializer, ProductSerializer


class ProductListView(ListAPIView):
    serializer_class = ProductSerializer

    def get_queryset(self):
        query_serializer = ProductListQuerySerializer(
            data=self.request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        queryset = Product.objects.all()

        search = params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(sku__icontains=search)
            )

        if "in_stock" in self.request.query_params:
            if params["in_stock"]:
                queryset = queryset.filter(stock__gt=0)
            else:
                queryset = queryset.filter(stock=0)

        min_price = params.get("min_price")
        if min_price is not None:
            queryset = queryset.filter(price__gte=min_price)

        max_price = params.get("max_price")
        if max_price is not None:
            queryset = queryset.filter(price__lte=max_price)

        return queryset.order_by(params["ordering"], "id")


class ProductDetailView(RetrieveAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

    def retrieve(self, request, *args, **kwargs):
        product_id = self.kwargs[self.lookup_field]
        cache_key = product_detail_cache_key(product_id)
        cached_data = cache.get(cache_key)

        if cached_data is not None:
            return Response(cached_data, headers={"X-Cache": "HIT"})

        product = self.get_object()
        product_data = dict(self.get_serializer(product).data)
        cache.set(cache_key, product_data)

        return Response(product_data, headers={"X-Cache": "MISS"})
