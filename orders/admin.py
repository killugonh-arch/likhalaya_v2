from django.contrib import admin
from .models import Order, OrderItem, GCashQRCode, GCashQRRemovalRequest, ShippingRate, ShippingSetting

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product_name', 'product_price', 'size', 'quantity', 'item_total']

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'full_name', 'email', 'total', 'status', 'payment_method', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['full_name', 'email', 'phone']
    list_editable = ['status']
    inlines = [OrderItemInline]
    readonly_fields = ['subtotal', 'shipping_fee', 'total', 'created_at', 'updated_at']

@admin.register(GCashQRCode)
class GCashQRCodeAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'uploaded_by', 'created_at', 'confirmed_at', 'deactivated_at']
    list_filter = ['status']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(GCashQRRemovalRequest)
class GCashQRRemovalRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'qr_code', 'reason', 'status', 'requested_by', 'decided_by', 'created_at']
    list_filter = ['status', 'reason']
    readonly_fields = ['created_at']


@admin.register(ShippingRate)
class ShippingRateAdmin(admin.ModelAdmin):
    list_display = ['province', 'city', 'barangay', 'base_fee', 'per_extra_item', 'is_active']
    list_filter = ['is_active', 'province']
    search_fields = ['province', 'city', 'barangay']


@admin.register(ShippingSetting)
class ShippingSettingAdmin(admin.ModelAdmin):
    list_display = ['per_extra_item', 'max_item_surcharge', 'updated_at']