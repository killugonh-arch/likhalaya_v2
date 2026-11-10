def customer_notifications(request):
    """Feeds the notification bell in base.html for logged-in customers.
    Shows the same notifications as the mobile app (no age cut-off)."""
    if not request.user.is_authenticated:
        return {'notifications': [], 'notification_count': 0}

    from .models import Notification
    qs = Notification.objects.filter(user=request.user).select_related('order')
    return {
        'notifications': qs[:8],
        'notification_count': qs.filter(is_read=False).count(),
    }