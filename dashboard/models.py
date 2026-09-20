from django.db import models
from django.core.exceptions import ValidationError
from accounts.models import CustomUser


# ──────────────────────────────────────────────────────────────────────────
# PDL Financial Reporting
#
# Scope (confirmed business rule): LikhaLaya only CALCULATES and REPORTS the
# amount available for PDL sharing. It does NOT track individual PDL members
# or manage actual payouts -- that is handled manually by the client outside
# this system. So there is deliberately no PDLMember / PDLDistribution /
# PDLPayout model here.
#
# PDL sharing is based on PRODUCT INCOME (Order.subtotal) only. Shipping
# fees (Order.shipping_fee) are always reported separately and never enter
# the PDL calculation.
# ──────────────────────────────────────────────────────────────────────────

class MonthlyPeriod(models.Model):
    """One calendar month's financial reporting period. Created lazily the
    first time a financial write action (adding an expense, setting the PDL
    rule, or finalizing) touches that month -- just viewing a month's report
    does not create a row.

    Deliberately named `status`/`is_finalized` (property) here rather than
    reusing Order.is_finalized, which means something unrelated (a confirmed
    vs. draft GCash order) -- see the audit notes on that naming collision.
    """
    STATUS_OPEN = 'open'
    STATUS_FINALIZED = 'finalized'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_FINALIZED, 'Finalized'),
    ]

    year = models.IntegerField()
    month = models.IntegerField()  # 1-12
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)

    finalized_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='finalized_periods'
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reopened_periods'
    )
    reopened_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    # -- Locked snapshot, written once at finalization time --
    # A finalized month's reported figures must never silently change later
    # just because an expense-approval or PDLAllocationRule edit happens
    # afterwards. These fields freeze the figures that were shown to the
    # client at the moment "Finalize Month" was pressed. When status is
    # FINALIZED, the reports view displays these instead of recomputing.
    locked_product_income = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    locked_shipping_income = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    locked_approved_expenses = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    locked_net_product_income = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    locked_pdl_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    locked_pdl_share_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year', '-month']
        constraints = [
            models.UniqueConstraint(fields=['year', 'month'], name='unique_monthly_period'),
        ]

    def __str__(self):
        return f"{self.month_name} {self.year} ({self.get_status_display()})"

    @property
    def month_name(self):
        import calendar
        try:
            return calendar.month_name[self.month]
        except (IndexError, TypeError):
            return str(self.month)

    @property
    def is_finalized(self):
        return self.status == self.STATUS_FINALIZED

    @classmethod
    def get_or_create_for(cls, year, month):
        obj, _ = cls.objects.get_or_create(year=year, month=month)
        return obj


class Expense(models.Model):
    """An approved deduction against a month's PRODUCT INCOME, used to
    calculate Net Product Income before the PDL share is taken. Only
    is_approved=True expenses are subtracted in the PDL calculation.
    A finalized MonthlyPeriod blocks new expenses and further edits."""

    CATEGORY_CHOICES = [
        ('materials', 'Materials'),
        ('utilities', 'Utilities'),
        ('wages', 'Wages'),
        ('logistics', 'Logistics'),
        ('other', 'Other'),
    ]

    period = models.ForeignKey(MonthlyPeriod, on_delete=models.CASCADE, related_name='expenses')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')

    added_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expenses_added'
    )
    added_at = models.DateTimeField(auto_now_add=True)

    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expenses_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.description} - Php{self.amount} ({self.period})"

    def clean(self):
        if self.period_id and self.period.is_finalized:
            raise ValidationError(
                "This month has already been finalized. Reopen it before adding or editing expenses."
            )


class PDLAllocationRule(models.Model):
    """The configurable PDL share percentage, applied to Net Product Income.
    Only one rule is is_active=True at a time. When a new percentage is set,
    the previous one is deactivated (not deleted), so historical finalized
    months can still be traced back to the rule that was in effect for them
    via MonthlyPeriod.locked_pdl_percentage."""

    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    effective_from = models.DateField()
    set_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pdl_rules_set'
    )
    set_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-effective_from', '-set_at']

    def __str__(self):
        return f"{self.percentage}% (from {self.effective_from})"

    @classmethod
    def active_percentage_as_of(cls, as_of_date):
        """The percentage that was in effect on/at the given date, based on
        effective_from. Used so a given month always uses the rule that
        applied at that month's end, not whatever is active "right now"."""
        rule = (cls.objects.filter(effective_from__lte=as_of_date)
                .order_by('-effective_from', '-set_at').first())
        return rule.percentage if rule else None

    def save(self, *args, **kwargs):
        if self.is_active:
            PDLAllocationRule.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)
