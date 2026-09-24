from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from chats.models import Conversation, ChatMessage
from .permissions import IsStaffRole

MAX_MESSAGE_LENGTH = 2000


def _message_json(message):
    """Matches ChatMessage.fromJson in lib/models/chat.dart exactly."""
    sender_name = ''
    if not message.from_customer:
        sender_name = message.sender.get_full_name() if message.sender else 'Likhalaya Team'
    return {
        'id': message.id,
        'body': message.body,
        'created_at': message.created_at.isoformat(),
        'from_customer': message.from_customer,
        'sender_name': sender_name,
        'read': message.read,
    }


def _conversation_json(conversation):
    """Matches ChatConversation.fromJson in lib/models/chat.dart exactly."""
    customer = conversation.customer
    last = conversation.last_message
    avatar = ''
    if customer.avatar:
        try:
            avatar = customer.avatar.url
        except ValueError:
            avatar = ''
    return {
        'id': conversation.id,
        'customer_id': customer.id,
        'customer_name': customer.get_full_name() or customer.username,
        'customer_email': customer.email,
        'customer_avatar': avatar,
        'unread': conversation.unread_for_staff,
        'last_message_at': (last.created_at if last else conversation.created_at).isoformat(),
        'last_message': last.body if last else '',
        'last_from_customer': last.from_customer if last else True,
    }


def _get_or_create_customer_conversation(user):
    conversation, _ = Conversation.objects.get_or_create(customer=user)
    return conversation


class ChatUnreadCountView(APIView):
    """GET /api/chat/unread/ -> {"count": n}
    Staff: total unread customer messages across every conversation.
    Customer: unread staff replies in their own thread."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.is_staff_user():
            count = ChatMessage.objects.filter(from_customer=True, read=False).count()
        else:
            count = ChatMessage.objects.filter(
                conversation__customer=user, from_customer=False, read=False,
            ).count()
        return Response({'count': count})


class ChatConversationsView(APIView):
    """GET /api/chat/conversations/?q=... -> {"conversations": [...]}
    Staff-only inbox of every customer thread, newest activity first."""
    permission_classes = [IsStaffRole]

    def get(self, request):
        qs = Conversation.objects.select_related('customer').prefetch_related('messages')
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(customer__first_name__icontains=q) |
                Q(customer__last_name__icontains=q) |
                Q(customer__username__icontains=q) |
                Q(customer__email__icontains=q)
            )
        conversations = [c for c in qs if c.messages.exists() or q]
        conversations.sort(
            key=lambda c: (c.last_message.created_at if c.last_message else c.created_at),
            reverse=True,
        )
        return Response({'conversations': [_conversation_json(c) for c in conversations]})


class ChatMessagesView(APIView):
    """
    GET  /api/chat/messages/?after=<id> -> {"messages": [...]}  (customer's own thread)
    POST /api/chat/messages/ {"body": "..."}                    (customer sends)
    Auto-creates the customer's conversation on first use.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        conversation = _get_or_create_customer_conversation(request.user)
        messages = conversation.messages.all()
        after = request.query_params.get('after')
        if after and after.isdigit():
            messages = messages.filter(id__gt=int(after))

        # Customer is viewing -> mark staff replies as read.
        conversation.messages.filter(from_customer=False, read=False).update(read=True)

        return Response({'messages': [_message_json(m) for m in messages]})

    def post(self, request):
        body = (request.data.get('body') or '').strip()
        if not body:
            return Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(body) > MAX_MESSAGE_LENGTH:
            return Response({'detail': 'Message is too long.'}, status=status.HTTP_400_BAD_REQUEST)

        conversation = _get_or_create_customer_conversation(request.user)
        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            from_customer=True,
            body=body,
            read=False,
        )
        return Response(_message_json(message), status=status.HTTP_201_CREATED)


class ChatConversationMessagesView(APIView):
    """
    GET  /api/chat/conversations/{id}/messages/?after=<id> -> {"messages": [...]}
    POST /api/chat/conversations/{id}/messages/ {"body": "..."}
    Staff-only: reply to a specific customer's thread.
    """
    permission_classes = [IsStaffRole]

    def get(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        messages = conversation.messages.all()
        after = request.query_params.get('after')
        if after and after.isdigit():
            messages = messages.filter(id__gt=int(after))

        conversation.messages.filter(from_customer=True, read=False).update(read=True)

        return Response({'messages': [_message_json(m) for m in messages]})

    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        body = (request.data.get('body') or '').strip()
        if not body:
            return Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(body) > MAX_MESSAGE_LENGTH:
            return Response({'detail': 'Message is too long.'}, status=status.HTTP_400_BAD_REQUEST)

        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            from_customer=False,
            body=body,
            read=False,
        )
        return Response(_message_json(message), status=status.HTTP_201_CREATED)