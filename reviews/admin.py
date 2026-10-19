from django.contrib import admin
from django.utils import timezone

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'reviewer_name', 'rating', 'short_comment',
                    'is_verified_purchase', 'is_visible', 'has_reply', 'created_at']
    list_filter = ['is_visible', 'rating', 'is_verified_purchase', 'created_at']
    list_editable = ['is_visible']
    search_fields = ['product__name', 'reviewer_name', 'comment', 'user__email']
    readonly_fields = ['created_at', 'updated_at', 'replied_by', 'replied_at']
    raw_id_fields = ['product', 'user']
    actions = ['hide_selected', 'show_selected']

    @admin.display(description='Comment')
    def short_comment(self, obj):
        return (obj.comment[:60] + '…') if len(obj.comment) > 60 else obj.comment

    @admin.display(boolean=True, description='Replied')
    def has_reply(self, obj):
        return bool(obj.staff_reply)

    def save_model(self, request, obj, form, change):
        if 'staff_reply' in form.changed_data:
            if obj.staff_reply.strip():
                obj.replied_by = request.user
                obj.replied_at = timezone.now()
            else:
                obj.replied_by = None
                obj.replied_at = None
        super().save_model(request, obj, form, change)

    @admin.action(description='Hide selected reviews')
    def hide_selected(self, request, queryset):
        self.message_user(request, f'{queryset.update(is_visible=False)} review(s) hidden.')

    @admin.action(description='Show selected reviews')
    def show_selected(self, request, queryset):
        self.message_user(request, f'{queryset.update(is_visible=True)} review(s) shown.')