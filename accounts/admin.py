from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, ActivityLog

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'role', 'is_active', 'created_at']
    list_filter = ['role', 'is_active', 'is_staff']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    fieldsets = UserAdmin.fieldsets + (
        ('Profile', {'fields': ('role', 'phone', 'address', 'avatar', 'bio')}),
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