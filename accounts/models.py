import random
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone
from datetime import timedelta


class ActiveUserManager(UserManager):
    """Default manager: hides archived (soft-deleted) accounts everywhere
    (login, dashboard lists, Django admin, etc). Use CustomUser.all_objects
    to include archived accounts, e.g. on the Archive page."""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('customer', 'Customer'),
        ('staff', 'Staff'),
        ('courier', 'Delivery Courier'),
        ('admin', 'Administrator'),
    ]
    email = models.EmailField('email address', unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='customer')
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True, help_text='House #, Street')
    barangay = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=10, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── Archive (soft-delete) ──
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_users'
    )

    objects = ActiveUserManager()
    all_objects = UserManager()

    class Meta:
        base_manager_name = 'all_objects'

    def save(self, *args, **kwargs):
        # Anyone set to role='admin' is automatically promoted to a real
        # Django superuser (and is_staff, which the built-in admin login
        # also requires) — so the Administrator role and full admin
        # access always stay in sync, instead of needing a separate
        # manual step.
        if self.role == 'admin':
            self.is_superuser = True
            self.is_staff = True
        super().save(*args, **kwargs)

    def is_admin_user(self):
        return self.role == 'admin' or self.is_superuser

    def is_staff_user(self):
        return self.role in ['admin', 'staff'] or self.is_superuser

    def is_courier_user(self):
        # 'staff' can also access the Deliveries pages (confirm delivery,
        # upload pickup proof) since staff sometimes ship orders
        # themselves instead of a dedicated courier — on top of their
        # normal full dashboard access from is_staff_user() above.
        return self.role in ['courier', 'staff']

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username

    def archive(self, by_user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.is_active = False
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'is_active'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.is_active = True
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'is_active'])

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class ActivityLog(models.Model):
    ACTION_CHOICES = [
        ('login', 'Logged In'),
        ('login_failed', 'Failed Login'),
        ('logout', 'Logged Out'),
        ('create', 'Created'),
        ('update', 'Updated'),
        ('delete', 'Deleted'),
        ('restore', 'Restored'),
        ('status_change', 'Status Change'),
        ('other', 'Other'),
    ]

    user = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='activity_logs'
    )
    # Snapshot so the log stays readable even if the account is later deleted.
    username = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='other')
    description = models.CharField(max_length=255, blank=True)

    STATUS_CHOICES = [
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]
    # What kind of thing was touched (e.g. Product, Order, User, Category)
    # and a human-readable label for that specific record (e.g. its name/number).
    resource = models.CharField(max_length=50, blank=True)
    resource_label = models.CharField(max_length=255, blank=True)
    previous_value = models.CharField(max_length=255, blank=True)
    new_value = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='success')

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.username or 'Unknown'} - {self.get_action_display()} - {self.timestamp:%Y-%m-%d %H:%M}"


class EmailOTP(models.Model):
    """One-time 6-digit code emailed to a user's Gmail (or any email) address
    to confirm they own it before their account is activated."""
    user = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.CASCADE, related_name='email_otps'
    )
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    OTP_VALID_MINUTES = 2
    OTP_MAX_ATTEMPTS = 5

    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def generate_for_user(cls, user):
        """Invalidate any previous unused codes and issue a fresh one."""
        cls.objects.filter(user=user, is_used=False).update(is_used=True)
        code = f"{random.randint(0, 999999):06d}"
        return cls.objects.create(user=user, code=code)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=self.OTP_VALID_MINUTES)

    def is_valid(self):
        return not self.is_used and not self.is_expired() and self.attempts < self.OTP_MAX_ATTEMPTS

    def __str__(self):
        return f"OTP for {self.user.username} ({'used' if self.is_used else 'active'})"