import io
import uuid

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from PIL import Image, ImageOps, UnidentifiedImageError

from chats.models import Conversation, ChatMessage
from .permissions import IsStaffRole

MAX_MESSAGE_LENGTH = 2000

# Photos sent in chat.
MAX_CHAT_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
CHAT_IMAGE_FORMATS = {'JPEG': ('.jpg', '.jpeg'), 'PNG': ('.png',), 'WEBP': ('.webp',)}
MAX_CHAT_IMAGE_PIXELS = 25_000_000
MAX_CHAT_IMAGE_SIDE = 8000


def _clean_chat_image(upload):
    """Checks an uploaded chat photo and sanitizes it in place (same approach
    as orders.validators.validate_payment_proof): real image content, allowed
    type, sane size, then re-encoded from pixels so EXIF/GPS and any appended
    payload are dropped and the filename becomes random.
    Returns an error message, or None when the image is fine."""
    invalid = "That file doesn't look like a valid image (JPG, PNG or WEBP)."
    if upload.size > MAX_CHAT_IMAGE_SIZE:
        return 'That image is too large (must be under 5 MB).'
    name = (upload.name or '').lower()
    if '.' not in name:
        return invalid
    ext = '.' + name.rsplit('.', 1)[-1]
    try:
        upload.seek(0)
        probe = Image.open(upload)
        probe.verify()
        fmt = probe.format
        upload.seek(0)
        img = Image.open(upload)
        width, height = img.size
        if fmt not in CHAT_IMAGE_FORMATS or ext not in CHAT_IMAGE_FORMATS[fmt]:
            return invalid
        if width * height > MAX_CHAT_IMAGE_PIXELS or max(width, height) > MAX_CHAT_IMAGE_SIDE:
            return 'That image has unrealistic dimensions.'
        img = ImageOps.exif_transpose(img)
        buf = io.BytesIO()
        if fmt == 'JPEG':
            img.convert('RGB').save(buf, 'JPEG', quality=88, optimize=True)
            new_ext, ctype = '.jpg', 'image/jpeg'
        elif fmt == 'PNG':
            img.save(buf, 'PNG', optimize=True)
            new_ext, ctype = '.png', 'image/png'
        else:
            img.save(buf, 'WEBP', quality=88)
            new_ext, ctype = '.webp', 'image/webp'
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        return invalid
    finally:
        upload.seek(0)
    buf.seek(0)
    upload.file = buf
    upload.size = buf.getbuffer().nbytes
    upload.name = f'{uuid.uuid4().hex}{new_ext}'
    upload.content_type = ctype
    return None


def _image_url(message):
    if not getattr(message, 'image', None):
        return ''
    try:
        return message.image.url
    except ValueError:
        return ''


def _read_message_input(request):
    """Returns (body, image_upload, error_response). A message needs text,
    a photo, or both."""
    body = (request.data.get('body') or '').strip()
    image = request.FILES.get('image')
    if not body and not image:
        return None, None, Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(body) > MAX_MESSAGE_LENGTH:
        return None, None, Response({'detail': 'Message is too long.'}, status=status.HTTP_400_BAD_REQUEST)
    if image:
        error = _clean_chat_image(image)
        if error:
            return None, None, Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
    return body, image, None


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
        'image': _image_url(message),
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
        'last_message': (last.body or ('📷 Photo' if _image_url(last) else '')) if last else '',
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
    Auto-creates the customer's conversation on first use.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

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
        body, image, error = _read_message_input(request)
        if error:
            return error

        conversation = _get_or_create_customer_conversation(request.user)
        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            from_customer=True,
            body=body,
            image=image,
            read=False,
        )
        return Response(_message_json(message), status=status.HTTP_201_CREATED)


class ChatConversationMessagesView(APIView):
    """
    Staff-only: reply to a specific customer's thread.
    """
    permission_classes = [IsStaffRole]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

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
        body, image, error = _read_message_input(request)
        if error:
            return error

        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            from_customer=False,
            body=body,
            image=image,
            read=False,
        )
        return Response(_message_json(message), status=status.HTTP_201_CREATED)