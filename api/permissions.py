from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """Allows access only to users with role='admin' or is_superuser."""
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_admin_user())


class IsStaffRole(BasePermission):
    """Allows access to admin or staff roles (i.e. anyone
    who can see the dashboard side of Likhalaya)."""
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_staff_user())


class IsCustomerRole(BasePermission):
    """Allows access only to plain customers (buyers)."""
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.role == 'customer')


class IsOwnerOrStaff(BasePermission):
    """Object-level permission: the object's `user` field must match the
    requester, unless the requester is staff/admin."""
    def has_object_permission(self, request, view, obj):
        u = request.user
        if u.is_staff_user():
            return True
        owner = getattr(obj, 'user', None)
        return owner_id_matches(owner, u)


def owner_id_matches(owner, user):
    return owner is not None and owner.pk == user.pk