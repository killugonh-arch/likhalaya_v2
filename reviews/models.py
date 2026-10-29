from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Avg, Count, Q
from django.utils import timezone

from store.models import ActiveManager


def star_list(average):
    """Turn an average (0-5) into a list of 'full' / 'half' / 'empty' for
    rendering five stars. Rounds to the nearest half star."""
    rounded = round(float(average or 0) * 2) / 2
    full = int(rounded)
    half = (rounded - full) >= 0.5
    stars = ['full'] * full
    if half:
        stars.append('half')
    stars += ['empty'] * (5 - len(stars))
    return stars


class Review(models.Model):
    RATING_CHOICES = [(i, f"{i} star{'s' if i > 1 else ''}") for i in range(1, 6)]

    product = models.ForeignKey(
        'store.Product', on_delete=models.CASCADE, related_name='reviews'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviews'
    )
    # Snapshot of the name shown publicly (first name + last initial), so the
    # review stays readable even if the account is later removed. Never the
    # username/email.
    reviewer_name = models.CharField(max_length=150, blank=True)
    rating = models.PositiveSmallIntegerField(
        choices=RATING_CHOICES,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True, max_length=1000)
    is_verified_purchase = models.BooleanField(
        default=False,
        help_text="Customer has a delivered order containing this product."
    )

    # Moderation (dashboard / Django admin)
    is_visible = models.BooleanField(
        default=True,
        help_text="Untick to hide this review from the storefront and from the product rating."
    )
    staff_reply = models.TextField(blank=True, max_length=1000)
    replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    replied_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Archive (soft delete) — archived reviews are hidden everywhere and
    # listed in Dashboard > Archive > Reviews, where they can be restored.
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='deleted_reviews'
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = 'all_objects'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'user'],
                condition=Q(user__isnull=False),
                name='unique_review_per_user_per_product',
            ),
        ]
        indexes = [
            models.Index(fields=['product', 'is_visible', '-created_at']),
        ]

    def archive(self, by_user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def __str__(self):
        return f"{self.rating}★ on {self.product} by {self.reviewer_name or 'Customer'}"

    @property
    def display_name(self):
        return self.reviewer_name or 'Customer'

    @property
    def stars(self):
        return star_list(self.rating)


def public_name_for(user):
    """First name + last initial. Falls back to 'Customer' so the
    auto-generated username (derived from the email) is never exposed."""
    first = (user.first_name or '').strip()
    last = (user.last_name or '').strip()
    if first and last:
        return f"{first} {last[0].upper()}."
    return first or 'Customer'


def user_has_purchased(user, product):
    if not user or not user.is_authenticated:
        return False
    from orders.models import OrderItem
    return OrderItem.objects.filter(
        order__user=user, order__status='delivered', product=product
    ).exists()


def review_stats(product):
    """Average, count and 5→1 star breakdown over VISIBLE reviews only."""
    qs = Review.objects.filter(product=product, is_visible=True)
    agg = qs.aggregate(avg=Avg('rating'), total=Count('id'))
    total = agg['total'] or 0
    average = float(agg['avg'] or 0)
    counts = {r['rating']: r['n'] for r in qs.values('rating').annotate(n=Count('id'))}
    rows = [
        {
            'stars': s,
            'count': counts.get(s, 0),
            'percent': round(counts.get(s, 0) * 100 / total) if total else 0,
        }
        for s in range(5, 0, -1)
    ]
    return {
        'average': round(average, 1),
        'total': total,
        'rows': rows,
        'stars': star_list(average),
    }