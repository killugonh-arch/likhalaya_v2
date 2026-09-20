def customer_notifications(request):
    """Feeds the notification bell in base.html for logged-in customers.
    Notifications older than 2 days are no longer shown here (they still
    exist in the database, they're just hidden from the dropdown)."""
    if not request.user.is_authenticated:
        return {'notifications': [], 'notification_count': 0}

    from django.utils import timezone
    from datetime import timedelta
    from .models import Notification
    cutoff = timezone.now() - timedelta(days=2)
    qs = Notification.objects.filter(user=request.user, created_at__gte=cutoff).select_related('order')
    return {
        'notifications': qs[:8],
        'notification_count': qs.filter(is_read=False).count(),
    }