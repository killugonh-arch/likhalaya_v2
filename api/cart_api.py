"""Server-side shopping cart shared by the website and the mobile app.

GET /cart/   -> {"results": [{"product": {...}, "size": "M", "design": {...}|null, "quantity": 2}]}
PUT /cart/   body {"items": [{"product": 5, "size": "M", "design": 12|null, "quantity": 2}]}
             replaces the whole cart, then returns it like GET.
"""
from django.db import transaction
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from orders.models import CartItem
from store.models import Product, ProductDesign

from .serializers import ProductSerializer


def _design_json(d):
    try:
        stock = d.stock_for_size(None)
    except Exception:
        stock = getattr(d, 'stock', 0)
    return {
        'id': d.id,
        'title': d.title,
        'image': d.image.url if d.image else '',
        'stock': stock,
    }


def _payload(request):
    rows = (CartItem.objects.filter(user=request.user)
            .select_related('product', 'design').order_by('id'))
    out = []
    for r in rows:
        if r.product is None or not r.product.is_active:
            continue
        out.append({
            'product': ProductSerializer(r.product, context={'request': request}).data,
            'size': r.size,
            'design': _design_json(r.design) if r.design else None,
            'quantity': r.quantity,
        })
    return {'results': out}


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def cart(request):
    if request.method == 'PUT':
        items = request.data.get('items')
        if not isinstance(items, list):
            return Response({'detail': 'items must be a list.'}, status=400)
        rows, seen = [], set()
        for it in items:
            try:
                pid = int(it['product'])
                qty = int(it.get('quantity', 1))
                did = int(it['design']) if it.get('design') else None
            except (KeyError, TypeError, ValueError):
                continue
            if qty < 1:
                continue
            product = Product.objects.filter(id=pid, is_active=True).first()
            if product is None:
                continue
            if did and not ProductDesign.objects.filter(
                    Q(product_size__product=product) | Q(parent_product=product),
                    id=did, is_active=True).exists():
                continue
            size = (it.get('size') or '').upper()[:1]
            if not (product.has_size_pricing or product.has_variants):
                size = ''          # products without sizes never carry one
            key = (pid, size, did)
            if key in seen:
                continue
            seen.add(key)
            rows.append(CartItem(user=request.user, product=product, size=size,
                                 design_id=did, quantity=min(qty, 99)))
        with transaction.atomic():
            CartItem.objects.filter(user=request.user).delete()
            CartItem.objects.bulk_create(rows)
    return Response(_payload(request))