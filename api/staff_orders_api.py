"""Staff "Orders Management" endpoint for the mobile app.

GET /api/staff/orders/?q=<text>&status=<status>&payment=<method>

Returns every website order (newest first) to staff/admin accounts only,
the same list the web dashboard's Orders Management page shows.
Customers and couriers get 403.
"""
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Order
from .permissions import IsStaffRole
from .serializers import OrderSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsStaffRole])
def staff_orders(request):
    # Default manager already hides unfinalized GCash drafts.
    qs = (Order.objects
          .exclude(sales_channel=Order.CHANNEL_WALK_IN)   # walk-ins have their own page
          .select_related('user')
          .prefetch_related('items')
          .order_by('-created_at'))

    q = (request.GET.get('q') or '').strip()
    if q:
        number = q.upper().replace('LKL-', '').lstrip('0')
        cond = (Q(full_name__icontains=q) | Q(email__icontains=q) |
                Q(user__username__icontains=q))
        if number.isdigit():
            cond |= Q(pk=int(number))
        qs = qs.filter(cond)

    status = request.GET.get('status')
    if status in dict(Order.STATUS_CHOICES):
        qs = qs.filter(status=status)
    payment = request.GET.get('payment')
    if payment in Order.PAYMENT_LABELS:
        qs = qs.filter(payment_method=payment)

    orders = list(qs[:300])
    data = OrderSerializer(orders, many=True, context={'request': request}).data
    status_labels = dict(Order.STATUS_CHOICES)
    for row, o in zip(data, orders):
        row['status_display'] = status_labels.get(o.status, o.status)
        row['payment_method_display'] = Order.PAYMENT_LABELS.get(o.payment_method, o.payment_method)
    return Response({'results': data})
