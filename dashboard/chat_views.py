from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render

from chats.models import ChatMessage, Conversation

from .views import staff_required

MAX_MESSAGE_LENGTH = 2000


@staff_required
def chat_list(request):
    """Website inbox of every customer thread coming from the mobile app."""
    search = request.GET.get('q', '').strip()
    qs = (
        Conversation.objects.select_related('customer')
        .annotate(
            last_at=Max('messages__created_at'),
            unread=Count('messages', filter=Q(messages__from_customer=True, messages__read=False)),
        )
        .order_by('-last_at', '-created_at')
    )
    if search:
        qs = qs.filter(
            Q(customer__username__icontains=search)
            | Q(customer__email__icontains=search)
            | Q(customer__first_name__icontains=search)
            | Q(customer__last_name__icontains=search)
        )
    page_obj = Paginator(qs, 15).get_page(request.GET.get('page'))
    for convo in page_obj:
        convo.last_msg = convo.last_message
    return render(request, 'dashboard/messages/chats.html', {
        'conversations': page_obj,
        'page_obj': page_obj,
        'search': search,
        'total_unread': ChatMessage.objects.filter(from_customer=True, read=False).count(),
    })


@staff_required
def chat_detail(request, pk):
    convo = get_object_or_404(Conversation.objects.select_related('customer'), pk=pk)

    if request.method == 'POST':
        body = request.POST.get('body', '').strip()
        if not body:
            messages.error(request, 'Reply cannot be empty.')
        elif len(body) > MAX_MESSAGE_LENGTH:
            messages.error(request, f'Reply is too long (max {MAX_MESSAGE_LENGTH} characters).')
        else:
            ChatMessage.objects.create(
                conversation=convo,
                sender=request.user,
                from_customer=False,
                body=body,
                read=False,
            )
        return redirect('dashboard:chat_detail', pk=convo.pk)

    # Opening the thread marks the customer's messages as read by staff.
    convo.messages.filter(from_customer=True, read=False).update(read=True)
    thread = convo.messages.select_related('sender').order_by('created_at')
    return render(request, 'dashboard/messages/chat_detail.html', {
        'convo': convo,
        'thread': thread,
    })