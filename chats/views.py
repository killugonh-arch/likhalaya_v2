from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from chats.models import ChatMessage, Conversation
from store.models import ContactMessage
from django.db.models import Q

from .chat_helpers import chat_inbox
from .views import staff_required

MAX_MESSAGE_LENGTH = 2000


@staff_required
def chat_list(request):
    """App chats now live inside the Messages page; keep the old URL working."""
    return redirect('dashboard:message_list')


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

    read_filter = request.GET.get('read', '')
    search = request.GET.get('q', '')
    inbox_qs = ContactMessage.objects.order_by('-created_at').prefetch_related('replies')
    if read_filter in {'true', 'false'}:
        inbox_qs = inbox_qs.filter(is_read=(read_filter == 'true'))
    if search:
        inbox_qs = inbox_qs.filter(Q(name__icontains=search) | Q(subject__icontains=search) | Q(email__icontains=search))

    last = thread.last()
    return render(request, 'dashboard/messages/detail.html', {
        'convo': convo,
        'thread': thread,
        'last_activity_at': last.created_at if last else convo.created_at,
        'chat_rows': chat_inbox(search, read_filter),
        'inbox_messages': inbox_qs[:50],
        'read_filter': read_filter,
        'search': search,
    })