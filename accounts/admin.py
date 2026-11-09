from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, ActivityLog, StaffInvite

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'role', 'mobile_access', 'mobile_only', 'is_active', 'created_at']
    list_filter = ['role', 'mobile_access', 'is_active', 'is_staff']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    fieldsets = UserAdmin.fieldsets + (
        ('Profile', {'fields': ('role', 'phone', 'address', 'avatar', 'bio')}),
        ('Mobile app', {'fields': ('mobile_access', 'mobile_only')}),
    )


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'username', 'role', 'action', 'description', 'ip_address']
    list_filter = ['action', 'role']
    search_fields = ['username', 'description', 'ip_address']
    date_hierarchy = 'timestamp'
    readonly_fields = ['user', 'username', 'role', 'action', 'description', 'ip_address', 'timestamp']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(StaffInvite)
class StaffInviteAdmin(admin.ModelAdmin):
    """Add one to generate a code, then give the code to the new staff member."""
    list_display = ['code', 'note', 'created_at', 'expires_at', 'used_by']
    fields = ['code', 'note', 'expires_at', 'used_by', 'created_at']
    readonly_fields = ['code', 'used_by', 'created_at']

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)