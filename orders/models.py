from django.db import models, transaction
from django.utils import timezone
from datetime import timedelta
from accounts.models import CustomUser
from store.models import Product


class OrderStatusError(Exception):
    """Raised when a task-based status transition is attempted out of order
    (e.g. trying to confirm pickup on an order that isn't Confirmed yet)."""
    pass

class OrderManager(models.Manager):
    """Default manager: hides GCash draft orders that exist only because the
    customer uploaded a receipt but never actually tapped 'Confirm Order'.
    Every existing Order.objects.* call (dashboard stats, My Orders, API,
    notification badges, etc.) automatically excludes these drafts without
    needing to be touched individually. Use Order.all_objects when you
    specifically need to reach a draft (e.g. the GCash confirm step)."""
    def get_queryset(self):
        return super().get_queryset().filter(is_finalized=True)


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('confirmed', 'Confirmed'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]
    PAYMENT_CHOICES = [
        ('cod', 'Cash on Delivery'),
        ('gcash', 'GCash'),
        ('bank', 'Bank Transfer'),
    ]
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    previous_status = models.CharField(max_length=20, choices=STATUS_CHOICES, blank=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='cod')
    # Shipping info
    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    address = models.TextField()
    city = models.CharField(max_length=100)
    province = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=10)
    notes = models.TextField(blank=True)
    # GCash payment verification
    payment_proof = models.ImageField(upload_to='payment_proofs/', null=True, blank=True)
    payment_submitted_at = models.DateTimeField(null=True, blank=True)
    # Totals
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # False only for a GCash order that's been created to hold an uploaded
    # receipt but hasn't been confirmed yet (customer hasn't tapped "Confirm
    # Order"). Stock is not deducted and the cart is not cleared until this
    # flips to True. Every other order (COD, or GCash post-confirm) is True.
    is_finalized = models.BooleanField(default=True)

    # ── Task-based fulfillment workflow ──
    # Which of our own delivery personnel is handling this order. Only
    # this courier (or an admin) can act on the pickup/delivery tasks below.
    assigned_courier = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='courier_orders', limit_choices_to={'role': 'courier'},
    )
    # Proof the courier picked up the order from the workshop. Submitting
    # this is what automatically flips Confirmed -> Shipped.
    pickup_proof = models.ImageField(upload_to='pickup_proofs/', null=True, blank=True)
    pickup_confirmed_at = models.DateTimeField(null=True, blank=True)
    # Proof the courier handed the order to the customer. Submitting this
    # is what automatically flips Shipped -> Delivered.
    delivery_proof = models.ImageField(upload_to='delivery_proofs/', null=True, blank=True)
    delivery_confirmed_at = models.DateTimeField(null=True, blank=True)

    # ── Estimated delivery window (in days) ──
    # Set by admin/staff when the order is started (Processing) and
    # editable until it is delivered. Shown to the customer on their order
    # page, e.g. "2–3 days". Both blank = no estimate given yet.
    eta_days_min = models.PositiveSmallIntegerField(null=True, blank=True)
    eta_days_max = models.PositiveSmallIntegerField(null=True, blank=True)
    # When the estimate was set. The arrival dates are counted from here.
    eta_set_at = models.DateTimeField(null=True, blank=True)

    objects = OrderManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.pk} – {self.full_name}"

    @property
    def order_number(self):
        return f"LKL-{self.pk:05d}"

    @property
    def eta_display(self):
        """'2–3 days', '1 day', or '' when no estimate was set."""
        lo, hi = self.eta_days_min, self.eta_days_max
        if lo is None and hi is None:
            return ''
        lo = lo if lo is not None else hi
        hi = hi if hi is not None else lo
        if lo == hi:
            return f"{lo} day{'s' if lo != 1 else ''}"
        return f"{lo}\u2013{hi} days"

    @property
    def eta_date_display(self):
        """'Oct 21 – Oct 22, 2026', 'Oct 21, 2026', or '' when no estimate.
        Counted from when the estimate was set (falls back to the order's
        creation date for estimates saved before eta_set_at existed)."""
        lo, hi = self.eta_days_min, self.eta_days_max
        if lo is None and hi is None:
            return ''
        lo = lo if lo is not None else hi
        hi = hi if hi is not None else lo
        base = timezone.localtime(self.eta_set_at or self.created_at).date()
        start = base + timedelta(days=lo)
        end = base + timedelta(days=hi)
        if start == end:
            return f"{start:%b} {start.day}, {start.year}"
        if start.year == end.year:
            return f"{start:%b} {start.day} \u2013 {end:%b} {end.day}, {end.year}"
        return f"{start:%b} {start.day}, {start.year} \u2013 {end:%b} {end.day}, {end.year}"

    def set_eta(self, days_min, days_max):
        """Admin action: set (or clear, with both None) the estimated delivery
        window in days. Allowed until the order is delivered or cancelled."""
        if self.status not in ('pending', 'processing', 'confirmed', 'shipped'):
            raise OrderStatusError("The delivery estimate can't be changed for this order anymore.")
        if (days_min is None) != (days_max is None):
            raise OrderStatusError("Please fill in both the 'from' and 'to' days.")
        if days_min is not None:
            if not (1 <= days_min <= 60 and 1 <= days_max <= 60):
                raise OrderStatusError("Delivery days must be between 1 and 60.")
            if days_min > days_max:
                raise OrderStatusError("'From' days can't be more than 'to' days.")
        self.eta_days_min = days_min
        self.eta_days_max = days_max
        self.eta_set_at = timezone.now() if days_min is not None else None
        self.save(update_fields=['eta_days_min', 'eta_days_max', 'eta_set_at', 'updated_at'])

    def restock_items(self):
        """Add each item's quantity back to stock. Call once, right when an
        order transitions into 'cancelled' status. If the item was bought
        with a specific design, the stock goes back into that design's
        stock for that size; otherwise it goes back to the plain product
        stock, same as before."""
        for item in self.items.select_related('product', 'design').all():
            if item.design:
                item.design.restock(item.quantity)
            elif item.product:
                item.product.stock += item.quantity
                item.product.save(update_fields=['stock'])

    # ── Task-based workflow transitions ──
    # Each of these is the ONLY way its status change happens: nothing sets
    # status='processing'/'confirmed'/'shipped'/'delivered' directly outside
    # of these methods, so the status is always a side-effect of a real task
    # being completed rather than a free-form dropdown pick.

    def start_processing(self):
        """Admin action: 'Start Processing'. Pending -> Processing."""
        if self.status != 'pending':
            raise OrderStatusError("Only a Pending order can be moved to Processing.")
        self.status = 'processing'
        self.save(update_fields=['status', 'updated_at'])

    def mark_ready_for_delivery(self):
        """Admin action: 'Mark Ready for Delivery'. Processing -> Confirmed."""
        if self.status != 'processing':
            raise OrderStatusError("Only an order in Processing can be confirmed as ready for delivery.")
        self.status = 'confirmed'
        self.save(update_fields=['status', 'updated_at'])

    def assign_courier(self, courier):
        """Admin action: assign one of our delivery personnel to this order."""
        if courier is not None and not courier.is_courier_user():
            raise OrderStatusError(f"{courier} is not a Delivery Courier.")
        self.assigned_courier = courier
        self.save(update_fields=['assigned_courier', 'updated_at'])

    def confirm_pickup(self, proof_image):
        """Courier action: 'Confirm Pickup'. Requires a pickup proof image
        and only applies while the order is Confirmed. Successfully
        submitting the proof is what automatically becomes Shipped —
        the courier never picks 'Shipped' from anywhere."""
        if self.status != 'confirmed':
            raise OrderStatusError("Pickup can only be confirmed for an order that is Confirmed and ready for delivery.")
        if not proof_image:
            raise OrderStatusError("A pickup proof image is required.")
        self.pickup_proof = proof_image
        self.pickup_confirmed_at = timezone.now()
        self.status = 'shipped'
        self.save(update_fields=['pickup_proof', 'pickup_confirmed_at', 'status', 'updated_at'])

    def confirm_delivery(self, proof_image):
        """Courier action: 'Confirm Delivery'. Requires a delivery proof
        image and only applies while the order is Shipped. Successfully
        submitting the proof is what automatically becomes Delivered."""
        if self.status != 'shipped':
            raise OrderStatusError("Delivery can only be confirmed for an order that is Shipped.")
        if not proof_image:
            raise OrderStatusError("A delivery proof image is required.")
        self.delivery_proof = proof_image
        self.delivery_confirmed_at = timezone.now()
        self.status = 'delivered'
        self.save(update_fields=['delivery_proof', 'delivery_confirmed_at', 'status', 'updated_at'])

    def cancel(self):
        """Explicit, separate cancel action (not part of the linear task
        flow). Blocked once the order has already shipped or delivered."""
        if self.status in ('shipped', 'delivered', 'cancelled'):
            raise OrderStatusError("This order can no longer be cancelled.")
        self.previous_status = self.status
        self.status = 'cancelled'
        self.save(update_fields=['previous_status', 'status', 'updated_at'])
        self.restock_items()

    def undo_cancel(self):
        """Reverse an accidental cancel: put the order back to the status it
        had before, and take its items out of stock again (the exact opposite
        of restock_items). Refused if live stock can no longer cover the items."""
        if self.status != 'cancelled':
            raise OrderStatusError("Only a cancelled order can be restored.")
        items = list(self.items.select_related('product', 'design').all())
        short = []
        for item in items:
            if item.design:
                available, name = item.design.stock, (item.design.title or item.product_name)
            elif item.product:
                available, name = item.product.stock, item.product_name
            else:
                continue
            if item.quantity > available:
                short.append(name)
        if short:
            raise OrderStatusError(
                "Can't restore this order - not enough stock left for: " + ", ".join(short) + "."
            )
        restored = self.previous_status if self.previous_status in ('pending', 'processing', 'confirmed') else 'pending'
        with transaction.atomic():
            for item in items:
                if item.design:
                    item.design.deduct_stock(item.quantity)
                elif item.product:
                    item.product.stock = max(0, item.product.stock - item.quantity)
                    item.product.save(update_fields=['stock'])
            self.status = restored
            self.previous_status = ''
            self.save(update_fields=['status', 'previous_status', 'updated_at'])


class OrderItem(models.Model):
    SIZE_CHOICES = Product.SIZE_CHOICES

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=200)
    product_price = models.DecimalField(max_digits=10, decimal_places=2)
    size = models.CharField(max_length=1, choices=SIZE_CHOICES, blank=True)
    design = models.ForeignKey(
        'store.ProductDesign', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='order_items',
    )
    design_name = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.quantity}x {self.product_name}"

    @property
    def item_total(self):
        return self.product_price * self.quantity

    @property
    def size_display(self):
        return dict(self.SIZE_CHOICES).get(self.size, '')


class Notification(models.Model):
    """A per-customer notification, e.g. 'Your order has been shipped.'"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='notifications')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    contact_message = models.ForeignKey(
        'store.ContactMessage', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications'
    )
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user}: {self.message}"

    @property
    def url(self):
        if self.order_id:
            from django.urls import reverse
            return reverse('orders:order_detail', args=[self.order_id])
        if self.contact_message_id:
            from django.urls import reverse
            return reverse('store:my_message_detail', args=[self.contact_message_id])
        return '#'


# ──────────────────────────────────────────────────────────────────────────
# GCash QR Code Management
#
# The QR code customers scan at checkout (orders/gcash_payment*.html) used
# to be a hardcoded static image (imgs/gcash-qr.jpg). This makes it a real,
# database-backed, staff-manageable record with a locked/approval workflow:
# once Staff confirms a QR code it is locked and can only be replaced after
# an Admin approves a removal request. Admins can always bypass the lock.
# ──────────────────────────────────────────────────────────────────────────
class GCashQRCode(models.Model):
    STATUS_PENDING_CONFIRM = 'pending_confirm'
    STATUS_ACTIVE_LOCKED = 'active_locked'
    STATUS_REMOVAL_PENDING = 'removal_pending'
    STATUS_REMOVAL_APPROVED = 'removal_approved'
    STATUS_REMOVAL_REJECTED = 'removal_rejected'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_PENDING_CONFIRM, 'Pending Staff Confirmation'),
        (STATUS_ACTIVE_LOCKED, 'Active & Locked'),
        (STATUS_REMOVAL_PENDING, 'Removal Request Pending'),
        (STATUS_REMOVAL_APPROVED, 'Removal Approved'),
        (STATUS_REMOVAL_REJECTED, 'Removal Rejected'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    image = models.ImageField(upload_to='gcash_qr/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE_LOCKED)

    # Account name/number shown to customers alongside the QR at checkout.
    # Only an Administrator can set/change these (see dashboard.gcash_qr_admin_*).
    # The name is masked for display (see accounts_mask templatetag) — the
    # number is shown in full, customers need it to double check they're
    # sending to the right account.
    account_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=30, blank=True)

    uploaded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_qr_codes'
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Set once this record is superseded (deactivated) so history stays intact.
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"GCash QR #{self.pk} ({self.get_status_display()})"

    @property
    def is_locked(self):
        """Staff cannot edit/replace/remove while any of these hold."""
        return self.status in (
            self.STATUS_ACTIVE_LOCKED,
            self.STATUS_REMOVAL_PENDING,
            self.STATUS_REMOVAL_REJECTED,
        )

    @classmethod
    def get_active(cls):
        """The QR code currently shown to customers at checkout."""
        return cls.objects.filter(
            status__in=[cls.STATUS_ACTIVE_LOCKED, cls.STATUS_REMOVAL_PENDING, cls.STATUS_REMOVAL_REJECTED]
        ).order_by('-created_at').first()

    @classmethod
    def can_staff_upload_new(cls):
        """Staff may only upload a new QR when there's no locked/active one
        and no unconfirmed preview already waiting."""
        return not cls.objects.filter(
            status__in=[
                cls.STATUS_PENDING_CONFIRM, cls.STATUS_ACTIVE_LOCKED,
                cls.STATUS_REMOVAL_PENDING, cls.STATUS_REMOVAL_REJECTED,
            ]
        ).exists()

    @classmethod
    def get_pending_confirm(cls):
        """A just-uploaded QR still awaiting the staff Confirm & Activate tap."""
        return cls.objects.filter(status=cls.STATUS_PENDING_CONFIRM).order_by('-created_at').first()


class GCashQRRemovalRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Admin Approval'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    REASON_INCORRECT = 'incorrect'
    REASON_OUTDATED = 'outdated'
    REASON_DAMAGED = 'damaged'
    REASON_WRONG_ACCOUNT = 'wrong_account'
    REASON_OTHER = 'other'
    REASON_CHOICES = [
        (REASON_INCORRECT, 'QR code was uploaded incorrectly'),
        (REASON_OUTDATED, 'QR code is outdated'),
        (REASON_DAMAGED, 'QR code is damaged/unreadable'),
        (REASON_WRONG_ACCOUNT, 'Wrong GCash account'),
        (REASON_OTHER, 'Other reason'),
    ]

    qr_code = models.ForeignKey(GCashQRCode, on_delete=models.CASCADE, related_name='removal_requests')
    requested_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='qr_removal_requests'
    )
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default=REASON_OTHER)
    explanation = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    decided_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='qr_removal_decisions'
    )
    decision_reason = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Removal request #{self.pk} for QR #{self.qr_code_id} ({self.get_status_display()})"

    def get_reason_display_full(self):
        base = self.get_reason_display()
        if self.explanation:
            return f"{base} — {self.explanation}"
        return base