from decimal import Decimal
from django.utils import timezone
from rest_framework import viewsets, generics, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.models import CustomUser, EmailOTP
from accounts.views import _send_otp_email
from store.models import Category, Product, ContactMessage, MessageReply
from store.views import _customer_reply_cooldown_remaining
from orders.models import Order, OrderItem, Notification
from orders.validators import validate_payment_proof

from .serializers import (
    CustomTokenObtainPairSerializer, UserSerializer, RegisterSerializer,
    CategorySerializer, ProductSerializer, OrderSerializer,
    OrderStatusUpdateSerializer, NotificationSerializer,
    ContactMessageListSerializer, ContactMessageDetailSerializer,
    MessageReplySerializer, MessageReplyCreateSerializer,
)
from .permissions import IsStaffRole, IsAdminRole


# ── Auth ──────────────────────────────────────────────────────────

class LoginView(TokenObtainPairView):
    """POST {username, password} -> {access, refresh, role, username, full_name, ...}"""
    serializer_class = CustomTokenObtainPairSerializer
    throttle_scope = 'login'


class RegisterView(generics.CreateAPIView):
    queryset = CustomUser.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        otp = EmailOTP.generate_for_user(user)
        try:
            _send_otp_email(user, otp)
        except Exception:
            user.delete()
            return Response(
                {'detail': "We couldn't send the verification email. Please try again or contact support."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {'detail': 'Registered. Check your email for the verification code.',
             'user_id': user.id},
            status=status.HTTP_201_CREATED,
        )


class VerifyOTPView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'login'

    def post(self, request):
        user_id = request.data.get('user_id')
        code = request.data.get('code')
        try:
            user = CustomUser.all_objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return Response({'detail': 'Invalid user.'}, status=400)

        otp = user.email_otps.filter(is_used=False).order_by('-created_at').first()
        if not otp or not otp.is_valid():
            return Response({'detail': 'Code expired or invalid.'}, status=400)
        if otp.code != code:
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            return Response({'detail': 'Incorrect code.'}, status=400)

        otp.is_used = True
        otp.save(update_fields=['is_used'])
        user.is_active = True
        user.save(update_fields=['is_active'])
        return Response({'detail': 'Account verified. You can now log in.'})


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


# ── Store ─────────────────────────────────────────────────────────

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    lookup_field = 'slug'

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsStaffRole()]
        return [permissions.AllowAny()]

    def get_queryset(self):
        qs = Product.objects.all() if self.request.user.is_authenticated and \
            self.request.user.is_staff_user() else Product.objects.filter(is_active=True)
        category_slug = self.request.query_params.get('category')
        search = self.request.query_params.get('search')
        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


# ── Orders ────────────────────────────────────────────────────────

SHIPPING_FEE_THRESHOLD = Decimal('500')
SHIPPING_FEE = Decimal('80')  # adjust to match your actual store logic


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        u = self.request.user
        if u.is_staff_user():
            return Order.objects.all()
        return Order.objects.filter(user=u)

    def create(self, request, *args, **kwargs):
        """Expects: shipping fields + items: [{product, size, quantity}]"""
        items_data = request.data.get('items', [])
        if not items_data:
            return Response({'detail': 'No items provided.'}, status=400)

        subtotal = Decimal('0')
        resolved_items = []
        for entry in items_data:
            try:
                product = Product.objects.get(pk=entry['product'])
            except Product.DoesNotExist:
                return Response({'detail': f"Product {entry.get('product')} not found."}, status=400)
            qty = int(entry.get('quantity', 1))
            if qty > product.stock:
                return Response({'detail': f"Not enough stock for {product.name}."}, status=400)
            size = entry.get('size', '')
            price = product.get_price_for_size(size)
            subtotal += price * qty
            resolved_items.append((product, size, qty, price))

        shipping_fee = Decimal('0') if subtotal >= SHIPPING_FEE_THRESHOLD else SHIPPING_FEE
        order = Order.objects.create(
            user=request.user,
            payment_method=request.data.get('payment_method', 'cod'),
            full_name=request.data.get('full_name', request.user.get_full_name()),
            email=request.data.get('email', request.user.email),
            phone=request.data.get('phone', request.user.phone),
            address=request.data.get('address', request.user.address),
            city=request.data.get('city', request.user.city),
            province=request.data.get('province', request.user.province),
            zip_code=request.data.get('zip_code', request.user.zip_code),
            notes=request.data.get('notes', ''),
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            total=subtotal + shipping_fee,
        )
        for product, size, qty, price in resolved_items:
            OrderItem.objects.create(
                order=order, product=product, product_name=product.name,
                product_price=price, size=size, quantity=qty,
            )
            product.stock -= qty
            product.save(update_fields=['stock'])

        serializer = self.get_serializer(order)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """POST /api/orders/{id}/cancel/ — the order's own customer may
        cancel it while it's still in an early status; mirrors
        orders.views.cancel_order on the web side."""
        order = self.get_object()
        if order.user_id != request.user.pk and not request.user.is_staff_user():
            return Response({'detail': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)
        if order.status in ['shipped', 'delivered', 'cancelled']:
            return Response({'detail': 'This order can no longer be cancelled.'}, status=400)
        order.previous_status = order.status
        order.status = 'cancelled'
        order.save(update_fields=['status', 'previous_status', 'updated_at'])
        order.restock_items()
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def upload_payment_proof(self, request, pk=None):
        """POST multipart /api/orders/{id}/upload_payment_proof/ with a
        `payment_proof` file — mirrors orders.views.gcash_payment's upload
        step. Only the order's own customer may attach a receipt."""
        order = self.get_object()
        if order.user_id != request.user.pk:
            return Response({'detail': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)
        proof = request.FILES.get('payment_proof')
        if not proof:
            return Response({'detail': 'Please attach a screenshot of your GCash payment.'}, status=400)
        error = validate_payment_proof(proof)
        if error:
            return Response({'detail': error}, status=400)
        order.payment_proof = proof
        order.payment_submitted_at = timezone.now()
        order.save(update_fields=['payment_proof', 'payment_submitted_at'])
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['patch'], permission_classes=[IsStaffRole])
    def set_status(self, request, pk=None):
        """PATCH /api/orders/{id}/set_status/ {status: 'shipped'} — staff/admin only."""
        order = self.get_object()
        serializer = OrderStatusUpdateSerializer(order, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']
        if new_status == 'cancelled' and order.status != 'cancelled':
            order.restock_items()
        order.previous_status = order.status
        order.status = new_status
        update_fields = ['status', 'previous_status', 'updated_at']
        # Financial reports recognize revenue using delivery_confirmed_at.
        # This endpoint bypasses Order.confirm_delivery() (no proof image is
        # available through this API action), so without this, orders moved
        # to 'delivered' here would carry a NULL delivery_confirmed_at and
        # silently drop out of every monthly financial report.
        if new_status == 'delivered' and order.delivery_confirmed_at is None:
            order.delivery_confirmed_at = timezone.now()
            update_fields.append('delivery_confirmed_at')
        order.save(update_fields=update_fields)
        return Response(OrderSerializer(order).data)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=['patch'])
    def mark_read(self, request, pk=None):
        notif = self.get_object()
        notif.is_read = True
        notif.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notif).data)


# ── Admin/Staff: user management ────────────────────────────────────

class UserManagementViewSet(viewsets.ModelViewSet):
    """Admin-only: list/manage accounts (mirrors your dashboard user admin)."""
    queryset = CustomUser.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminRole]
    http_method_names = ['get', 'patch', 'head', 'options']


# ── Messages (in-app chat) ──────────────────────────────────────────
# Same ContactMessage/MessageReply data the website's "My Messages" pages
# use — the app and the site read/write the exact same threads, so a reply
# sent on one shows up on the other.

class ContactMessageViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/messages/          -> list the current user's threads
    GET /api/messages/{id}/     -> one thread with its full reply history
    POST /api/messages/{id}/reply/  -> send a reply on that thread
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = ContactMessage.objects.all() if user.is_staff_user() else ContactMessage.objects.filter(customer=user)
        return qs.prefetch_related('replies').order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ContactMessageDetailSerializer
        return ContactMessageListSerializer

    def retrieve(self, request, *args, **kwargs):
        thread = self.get_object()
        # Mark the other side's replies as read now that this user is viewing.
        if request.user.is_staff_user():
            thread.replies.filter(is_staff_reply=False, is_read_by_staff=False).update(is_read_by_staff=True)
        else:
            thread.replies.filter(is_staff_reply=True, is_read_by_customer=False).update(is_read_by_customer=True)
        return Response(ContactMessageDetailSerializer(thread).data)

    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        thread = self.get_object()
        is_staff = request.user.is_staff_user()

        if not is_staff:
            cooldown = _customer_reply_cooldown_remaining(thread, request.user)
            if cooldown > 0:
                return Response(
                    {'detail': f'Please wait {cooldown}s before sending another message.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        serializer = MessageReplyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_reply = MessageReply.objects.create(
            thread=thread,
            staff=request.user if is_staff else None,
            is_staff_reply=is_staff,
            body=serializer.validated_data['body'],
            is_read_by_customer=not is_staff,
            is_read_by_staff=is_staff,
        )

        if not is_staff and thread.status in (ContactMessage.STATUS_RESOLVED, ContactMessage.STATUS_CLOSED):
            thread.status = ContactMessage.STATUS_UNDER_REVIEW
            thread.save(update_fields=['status'])

        return Response(MessageReplySerializer(new_reply).data, status=status.HTTP_201_CREATED)