from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from accounts.models import CustomUser
from store.models import Category, Product, ProductImage, ContactMessage, MessageReply
from orders.models import Order, OrderItem, Notification


# ── Auth ──────────────────────────────────────────────────────────

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds role + basic profile info directly into the JWT payload so the
    mobile app can route to the right screens without an extra request."""
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['username'] = user.username
        token['full_name'] = user.get_full_name()
        token['is_staff_role'] = user.is_staff_user()
        token['is_admin_role'] = user.is_admin_user()
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['role'] = self.user.role
        data['username'] = self.user.username
        data['full_name'] = self.user.get_full_name()
        data['is_staff_role'] = self.user.is_staff_user()
        data['is_admin_role'] = self.user.is_admin_user()
        return data


AVATAR_MAX_SIZE = 2 * 1024 * 1024  # 2 MB, same cap as the web ProfileUpdateForm


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'role', 'phone', 'address', 'barangay', 'city', 'province',
            'zip_code', 'avatar', 'bio', 'created_at',
        ]
        read_only_fields = ['id', 'email', 'role', 'created_at']

    def validate_avatar(self, value):
        if value and value.size > AVATAR_MAX_SIZE:
            raise serializers.ValidationError('Profile picture must be under 2 MB.')
        return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password', 'password2', 'first_name', 'last_name', 'phone']

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password2'):
            raise serializers.ValidationError({'password2': ["Passwords don't match."]})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        password = validated_data.pop('password')
        user = CustomUser(**validated_data, role='customer')
        user.set_password(password)
        user.is_active = False  # activated after EmailOTP verification
        user.save()
        return user


# ── Store ─────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'image', 'order', 'is_active']


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'caption']


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    extra_images = ProductImageSerializer(many=True, read_only=True)
    price_display = serializers.CharField(read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    has_size_pricing = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'category', 'category_name', 'name', 'slug', 'description',
            'price_min', 'price_medium', 'price_max', 'price_display',
            'has_size_pricing', 'stock', 'in_stock', 'image', 'extra_images',
            'gcash_qr_code', 'is_active', 'artisan_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        # On update (an instance already exists), only an Admin may submit a
        # value for gcash_qr_code. Making the field read-only for everyone
        # else means DRF drops it from validated_data entirely, so a Staff
        # user's request cannot alter it no matter what the request body
        # contains — this mirrors the dashboard ProductForm's enforcement.
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        is_admin = bool(request and request.user and request.user.is_authenticated
                         and request.user.is_admin_user())
        if self.instance is not None and not is_admin:
            self.fields['gcash_qr_code'].read_only = True


# ── Orders ────────────────────────────────────────────────────────

class OrderItemSerializer(serializers.ModelSerializer):
    item_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    size_display = serializers.CharField(read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'product_name', 'product_price', 'size',
            'size_display', 'quantity', 'item_total',
        ]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    order_number = serializers.CharField(read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'user', 'status', 'payment_method',
            'full_name', 'email', 'phone', 'address', 'city', 'province',
            'zip_code', 'notes', 'payment_proof', 'payment_submitted_at',
            'subtotal', 'shipping_fee', 'total', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'subtotal', 'shipping_fee', 'total',
                             'created_at', 'updated_at']


class OrderStatusUpdateSerializer(serializers.ModelSerializer):
    """Restricted serializer for staff/admin: status changes only."""
    class Meta:
        model = Order
        fields = ['status']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'order', 'message', 'is_read', 'created_at']
        read_only_fields = ['id', 'order', 'message', 'created_at']


# ── Messages (in-app chat: same ContactMessage/MessageReply threads used
#    by the website's "My Messages" pages) ─────────────────────────────

class MessageReplySerializer(serializers.ModelSerializer):
    sender_label = serializers.SerializerMethodField()

    class Meta:
        model = MessageReply
        fields = [
            'id', 'thread', 'is_staff_reply', 'sender_label', 'body',
            'is_read_by_customer', 'is_read_by_staff', 'created_at',
        ]
        read_only_fields = [
            'id', 'thread', 'is_staff_reply', 'sender_label',
            'is_read_by_customer', 'is_read_by_staff', 'created_at',
        ]

    def get_sender_label(self, obj):
        return 'Likhalaya Team' if obj.is_staff_reply else 'You'


class MessageReplyCreateSerializer(serializers.ModelSerializer):
    """Used only for POSTing a new reply onto an existing thread."""
    class Meta:
        model = MessageReply
        fields = ['body']

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Message cannot be empty.')
        return value


class ContactMessageListSerializer(serializers.ModelSerializer):
    """Lightweight — for the inbox list (no full reply history)."""
    has_unread = serializers.SerializerMethodField()
    last_reply_at = serializers.SerializerMethodField()

    class Meta:
        model = ContactMessage
        fields = [
            'id', 'inquiry_type', 'subject', 'message', 'status',
            'has_unread', 'last_reply_at', 'created_at',
        ]

    def get_has_unread(self, obj):
        request = self.context.get('request')
        if request and request.user.is_staff_user():
            return obj.has_unread_for_staff
        return obj.has_unread_for_customer

    def get_last_reply_at(self, obj):
        last = obj.replies.order_by('-created_at').first()
        return last.created_at if last else obj.created_at


class ContactMessageDetailSerializer(serializers.ModelSerializer):
    """Full thread with its replies, for the conversation screen."""
    replies = MessageReplySerializer(many=True, read_only=True)

    class Meta:
        model = ContactMessage
        fields = [
            'id', 'inquiry_type', 'subject', 'message', 'status',
            'replies', 'created_at',
        ]
        read_only_fields = fields