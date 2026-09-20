from django.urls import reverse
from store.models import Category, ContactMessage
from orders.models import Order
from orders.cart import Cart


def global_context(request):
    nav_categories = Category.objects.filter(is_active=True).order_by('order', 'name')[:10]
    cart = Cart(request)
    cart_count = cart.product_count()

    new_orders_count = 0
    new_messages_count = 0
    new_deliveries_count = 0
    notifications = []
    notification_count = 0

    if request.user.is_authenticated and hasattr(request.user, 'is_staff_user') and request.user.is_staff_user():
        pending_orders = Order.objects.filter(status='pending').order_by('-created_at')[:8]
        unread_messages = ContactMessage.objects.filter(is_read=False).order_by('-created_at')[:8]

        new_orders_count = Order.objects.filter(status='pending').count()
        new_messages_count = ContactMessage.objects.filter(is_read=False).count()
        notification_count = new_orders_count + new_messages_count

        items = []
        for order in pending_orders:
            items.append({
                'message': f'New pending order #{order.id} from {order.full_name}',
                'is_read': False,
                'created_at': order.created_at,
                'url': reverse('dashboard:order_detail', args=[order.id]),
            })
        for msg in unread_messages:
            items.append({
                'message': f'New message: {msg.subject}',
                'is_read': False,
                'created_at': msg.created_at,
                'url': reverse('dashboard:message_detail', args=[msg.id]),
            })
        items.sort(key=lambda i: i['created_at'], reverse=True)
        notifications = items[:8]

    # Deliveries badge — count of orders awaiting pickup/delivery this user
    # can act on: their own assigned deliveries, or (for admins) all of them.
    if request.user.is_authenticated and hasattr(request.user, 'is_courier_user') and request.user.is_courier_user():
        deliveries_qs = Order.objects.filter(status__in=['confirmed', 'shipped'])
        if not request.user.is_admin_user():
            deliveries_qs = deliveries_qs.filter(assigned_courier=request.user)
        new_deliveries_count = deliveries_qs.count()

    return {
        'nav_categories': nav_categories,
        'cart_count': cart_count,
        'new_orders_count': new_orders_count,
        'new_messages_count': new_messages_count,
        'new_deliveries_count': new_deliveries_count,
        'notifications': notifications,
        'notification_count': notification_count,
    }