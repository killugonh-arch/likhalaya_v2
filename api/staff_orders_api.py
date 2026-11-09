"""Staff "Orders Management" endpoints for the mobile app (put in api/).

GET  /staff/orders/                 list + search/filters (?q= &status= &payment=)
GET  /staff/orders/<id>/            one order, full detail
POST /staff/orders/<id>/action/     {"action": "start_processing" | "mark_ready" | "cancel" | "set_eta",
                                     "days_min": 2, "days_max": 3}   (days optional)

Staff/admin only (IsStaffRole). Status changes go through the Order model's own
methods (start_processing, mark_ready_for_delivery, cancel, set_eta), so the
same rules as the website apply.
"""
import importlib

from django.apps import apps
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .permissions import IsStaffRole


# ── Find the Order model without hard-coding its app name ──────────────────
def _find_model(name, must_have=None):
    for m in apps.get_models():
        if m._meta.object_name == name and (must_have is None or any(f.name == must_have for f in m._meta.get_fields())):
            return m
    raise LookupError(f'{name} model not found')


Order = _find_model('Order', must_have='sales_channel')
_models_mod = importlib.import_module(Order._meta.app_config.name + '.models')
OrderStatusError = _models_mod.OrderStatusError
Notification = _find_model('Notification')


def _log(request, action, order, before, after):
    """Record in the staff activity log (never breaks the request)."""
    try:
        mod = importlib.import_module(Order._meta.app_config.name + '.activity')
        mod.log_activity(request, 'update', f'Order {order.order_number}: {before} -> {after}',
                         resource='Order', resource_label=order.order_number,
                         previous_value=before, new_value=after)
    except Exception:
        pass


def _abs(request, f):
    try:
        return request.build_absolute_uri(f.url) if f else None
    except Exception:
        return None


def _item_image(request, item):
    for src in (getattr(item, 'design', None), getattr(item, 'product', None)):
        if src is None:
            continue
        for attr in ('image', 'default_variant_image', 'main_image'):
            url = _abs(request, getattr(src, attr, None))
            if url:
                return url
    return None


def _row(o, request):
    status_labels = dict(Order.STATUS_CHOICES)
    return {
        'id': o.pk,
        'order_number': o.order_number,
        'status': o.status,
        'status_display': status_labels.get(o.status, o.status),
        'payment_method': o.payment_method,
        'payment_method_display': Order.PAYMENT_LABELS.get(o.payment_method, o.payment_method),
        'full_name': o.full_name,
        'email': o.email,
        'phone': o.phone,
        'address': ', '.join(p for p in (o.address, o.barangay) if p),
        'city': o.city,
        'province': o.province,
        'zip_code': o.zip_code,
        'notes': o.notes,
        'subtotal': str(o.subtotal),
        'shipping_fee': str(o.shipping_fee),
        'total': str(o.total),
        'eta_days_min': o.eta_days_min,
        'eta_days_max': o.eta_days_max,
        'created_at': o.created_at.isoformat(),
        'updated_at': o.updated_at.isoformat(),
        'courier_name': (o.assigned_courier.get_full_name() or o.assigned_courier.get_username())
        if o.assigned_courier else None,
        'items': [{
            'id': i.pk,
            'product': i.product_id,
            'product_name': i.product_name,
            'product_price': str(i.product_price),
            'product_image': _item_image(request, i),
            'size': i.size,
            'size_display': i.size_display,
            'design_name': i.design_name,
            'quantity': i.quantity,
            'item_total': str(i.item_total),
        } for i in o.items.all()],
    }


def _qs():
    return (Order.objects
            .exclude(sales_channel=Order.CHANNEL_WALK_IN)   # walk-ins have their own page
            .select_related('user', 'assigned_courier')
            .prefetch_related('items__product', 'items__design'))


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsStaffRole])
def staff_orders(request):
    qs = _qs().order_by('-created_at')
    q = (request.GET.get('q') or '').strip()
    if q:
        number = q.upper().replace('LKL-', '').lstrip('0')
        cond = (Q(full_name__icontains=q) | Q(email__icontains=q) | Q(user__username__icontains=q))
        if number.isdigit():
            cond |= Q(pk=int(number))
        qs = qs.filter(cond)
    status = request.GET.get('status')
    if status in dict(Order.STATUS_CHOICES):
        qs = qs.filter(status=status)
    payment = request.GET.get('payment')
    if payment in Order.PAYMENT_LABELS:
        qs = qs.filter(payment_method=payment)
    return Response({'results': [_row(o, request) for o in qs[:300]]})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsStaffRole])
def staff_order_detail(request, pk):
    order = _qs().filter(pk=pk).first()
    if order is None:
        return Response({'detail': 'Order not found.'}, status=404)
    return Response(_row(order, request))


_NOTICE = {
    'processing': 'Your order {n} is now being processed.',
    'confirmed': 'Your order {n} is ready for delivery.',
    'cancelled': 'Your order {n} has been cancelled.',
}


def _days(v):
    if v in (None, ''):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise OrderStatusError('Delivery days must be whole numbers.')


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsStaffRole])
def staff_order_action(request, pk):
    order = _qs().filter(pk=pk).first()
    if order is None:
        return Response({'detail': 'Order not found.'}, status=404)

    action = request.data.get('action')
    before = order.status
    try:
        if action == 'start_processing':
            lo, hi = _days(request.data.get('days_min')), _days(request.data.get('days_max'))
            order.start_processing()
            if lo is not None or hi is not None:
                order.set_eta(lo, hi)
        elif action == 'mark_ready':
            order.mark_ready_for_delivery()
        elif action == 'cancel':
            order.cancel()
        elif action == 'set_eta':
            order.set_eta(_days(request.data.get('days_min')), _days(request.data.get('days_max')))
        else:
            return Response({'detail': 'Unknown action.'}, status=400)
    except OrderStatusError as e:
        return Response({'detail': str(e)}, status=400)

    if order.status != before:
        _log(request, action, order, before, order.status)
        if order.user_id and order.status in _NOTICE:
            try:
                Notification.objects.create(
                    user=order.user, order=order,
                    message=_NOTICE[order.status].format(n=order.order_number))
            except Exception:
                pass
    order.refresh_from_db()
    return Response(_row(_qs().get(pk=order.pk), request))