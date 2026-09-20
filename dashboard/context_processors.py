from orders.models import Order
from store.models import ContactMessage


def dashboard_notifications(request):
    if not request.user.is_authenticated:
        return {'new_orders_count': 0, 'new_messages_count': 0}

    if not getattr(request.user, 'is_staff_user', lambda: False)():
        return {'new_orders_count': 0, 'new_messages_count': 0}

    pending_orders_count = Order.objects.filter(status='pending').count()
    unread_messages_count = ContactMessage.objects.filter(is_read=False).count()
    return {
        'new_orders_count': pending_orders_count,
        'new_messages_count': unread_messages_count,
    }
