from django.contrib import admin
from .models import Category, Product, ProductImage, Personnel, ContactMessage, LivelihoodVideo

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'order', 'is_active', 'created_at']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['order', 'is_active']

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image', 'size', 'caption', 'order']

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price_min', 'price_medium', 'price_max', 'stock', 'is_active', 'created_at']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'description', 'artisan_name']
    list_editable = ['is_active', 'stock']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductImageInline]

@admin.register(Personnel)
class PersonnelAdmin(admin.ModelAdmin):
    list_display = ['rank', 'name', 'title', 'department_badge', 'order', 'is_active']
    list_editable = ['order', 'is_active']


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'inquiry_type', 'email', 'subject', 'status', 'created_at', 'is_read']
    list_filter = ['inquiry_type', 'status', 'is_read', 'created_at']
    search_fields = ['name', 'email', 'subject', 'message', 'item_name', 'organization_name', 'order_number_ref']
    list_editable = ['is_read']
    readonly_fields = ['created_at']
    fieldsets = (
        ('Contact Details', {'fields': ('inquiry_type', 'status', 'name', 'email', 'phone', 'subject', 'message',
                                         'customer', 'is_read', 'created_at')}),
        ('Product / Order Reference', {
            'fields': ('product', 'order', 'order_number_ref'),
        }),
        ('Product / Order Details', {
            'classes': ('collapse',),
            'fields': ('item_name', 'quantity', 'customization_request', 'preferred_materials',
                       'target_budget', 'preferred_date', 'reference_image'),
        }),
        ('Organization / Partnership Details', {
            'classes': ('collapse',),
            'fields': ('organization_name', 'partnership_type', 'partnership_details', 'materials_condition'),
        }),
        ('Feedback / Concern Details', {
            'classes': ('collapse',),
            'fields': ('feedback_type', 'related_product', 'concern_type'),
        }),
        ('Additional Notes', {'fields': ('additional_details', 'staff_notes')}),
    )


@admin.register(LivelihoodVideo)
class LivelihoodVideoAdmin(admin.ModelAdmin):
    list_display = ['title', 'order', 'is_active', 'show_on_home', 'created_at']
    list_editable = ['order', 'is_active', 'show_on_home']