from django.contrib import admin
from .models import MonthlyPeriod, Expense, PDLAllocationRule


@admin.register(MonthlyPeriod)
class MonthlyPeriodAdmin(admin.ModelAdmin):
    list_display = ('year', 'month', 'status', 'finalized_at', 'locked_pdl_share_amount')
    list_filter = ('status', 'year')
    readonly_fields = (
        'locked_product_income', 'locked_shipping_income', 'locked_approved_expenses',
        'locked_net_product_income', 'locked_pdl_percentage', 'locked_pdl_share_amount',
    )


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('description', 'amount', 'category', 'period', 'is_approved', 'added_at')
    list_filter = ('is_approved', 'category', 'period')
    search_fields = ('description',)


@admin.register(PDLAllocationRule)
class PDLAllocationRuleAdmin(admin.ModelAdmin):
    list_display = ('percentage', 'effective_from', 'is_active', 'set_at')
    list_filter = ('is_active',)
