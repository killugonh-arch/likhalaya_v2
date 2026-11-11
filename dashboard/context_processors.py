from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from reviews.models import Review
from store.models import ContactMessage


def _ago(dt):
    secs = int((timezone.now() - dt).total_seconds())
    if secs < 60:
        return 'now'
    if secs < 3600:
        return f'{secs // 60}m'
    if secs < 86400:
        return f'{secs // 3600}h'
    if secs < 86400 * 30:
        return f'{secs // 86400}d'
    return f'{secs // (86400 * 30)}mo'


def dashboard_notifications(request):
    empty = {
        'new_orders_count': 0, 'new_messages_count': 0, 'new_reviews_count': 0,
        'notif_orders': [], 'notif_messages': [], 'notif_reviews': [],
    }

    if not request.user.is_authenticated:
        return empty

    if not getattr(request.user, 'is_staff_user', lambda: False)():
        return empty

    pending_orders_count = Order.objects.filter(status='pending').count()
    unread_messages_count = ContactMessage.objects.filter(is_read=False).count()

    # Reviews that still have no staff reply
    unreplied_reviews_count = Review.objects.filter(
        Q(staff_reply__isnull=True) | Q(staff_reply='')
    ).count()

    # Specific recent items for the bell dropdown (2 per section)
    notif_orders = [
        {
            'title': f'Order #{o.pk}',
            'sub': f'{o.full_name} \u00b7 Pending',
            'url': reverse('dashboard:order_detail', args=[o.pk]),
            'ago': _ago(o.created_at),
        }
        for o in Order.objects.filter(status='pending').order_by('-created_at')[:2]
    ]
    notif_messages = [
        {
            'title': m.subject or m.get_inquiry_type_display(),
            'sub': f'{m.name} \u00b7 {m.get_inquiry_type_display()}',
            'url': reverse('dashboard:message_detail', args=[m.pk]),
            'ago': _ago(m.created_at),
        }
        for m in ContactMessage.objects.filter(is_read=False).order_by('-created_at')[:2]
    ]
    notif_reviews = [
        {
            'title': f'{r.rating}\u2605 on {r.product}',
            'sub': f'{r.reviewer_name or "Customer"} \u00b7 No reply yet',
            'url': reverse('reviews:dashboard_list'),
            'ago': _ago(r.created_at),
        }
        for r in Review.objects.filter(
            Q(staff_reply__isnull=True) | Q(staff_reply='')
        ).select_related('product').order_by('-created_at')[:2]
    ]

    return {
        'new_orders_count': pending_orders_count,
        'new_messages_count': unread_messages_count,
        'new_reviews_count': unreplied_reviews_count,
        'notif_orders': notif_orders,
        'notif_messages': notif_messages,
        'notif_reviews': notif_reviews,
    }