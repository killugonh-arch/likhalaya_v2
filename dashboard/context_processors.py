from django.db.models import Q

from orders.models import Order
from reviews.models import Review
from store.models import ContactMessage


def dashboard_notifications(request):
    empty = {'new_orders_count': 0, 'new_messages_count': 0, 'new_reviews_count': 0}

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

    return {
        'new_orders_count': pending_orders_count,
        'new_messages_count': unread_messages_count,
        'new_reviews_count': unreplied_reviews_count,
    }