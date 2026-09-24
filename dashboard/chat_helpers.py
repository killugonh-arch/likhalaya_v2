from django.db.models import Count, Max, Q

from chats.models import ChatMessage, Conversation


def chat_inbox(search='', read_filter='', limit=50):
    """App-chat conversations shaped for the Messages inbox.
    Same search / read filter as the inquiry inbox so both lists behave as one."""
    qs = (
        Conversation.objects.select_related('customer')
        .annotate(
            last_at=Max('messages__created_at'),
            unread=Count('messages', filter=Q(messages__from_customer=True, messages__read=False)),
        )
        .filter(last_at__isnull=False)
        .order_by('-last_at')
    )
    if search:
        qs = qs.filter(
            Q(customer__username__icontains=search)
            | Q(customer__email__icontains=search)
            | Q(customer__first_name__icontains=search)
            | Q(customer__last_name__icontains=search)
            | Q(pk__in=ChatMessage.objects.filter(body__icontains=search).values('conversation_id'))
        )
    if read_filter == 'false':
        qs = qs.filter(unread__gt=0)
    elif read_filter == 'true':
        qs = qs.filter(unread=0)
    rows = list(qs[:limit])
    for c in rows:
        c.display_name = c.customer.get_full_name() or c.customer.username
        c.last_msg = c.last_message
    return rows