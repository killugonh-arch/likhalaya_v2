import logging

from django.core.cache import cache
from django.http import Http404

logger = logging.getLogger('security')

ADMIN_MAX_ATTEMPTS = 5
ADMIN_LOCKOUT_SECONDS = 15 * 60

# idle timeouts (sliding: resets on every request)
CUSTOMER_IDLE_TIMEOUT_SECONDS = 2 * 24 * 60 * 60   # 2 days
STAFF_IDLE_TIMEOUT_SECONDS = 15 * 24 * 60 * 60     # 15 days (staff + admin)


def _client_ip(request):
    # Use the same proxy-aware resolver as django-axes (honours
    # DJANGO_BEHIND_PROXY / DJANGO_PROXY_COUNT) so a client can't spoof
    # X-Forwarded-For to dodge or trigger the /admin/ lockout.
    from likhalaya_project.rate_limit import get_client_ip
    return get_client_ip(request)


class StaffIdleTimeoutMiddleware:
    """Logs out customers after 2 days idle, staff/admin after 15 days idle.
    The timer resets on each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        # Mobile-only staff must never hold a website session (this also
        # covers Google web sign-in and sessions that already existed).
        if (user is not None and user.is_authenticated
                and getattr(user, 'role', '') == 'staff' and user.mobile_only):
            from django.contrib.auth import logout
            logout(request)
            return self.get_response(request)
        response = self.get_response(request)

        # Set the expiry AFTER the view runs so it also applies on the very
        # request where the user logs in (and skips users who just logged out).
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            if user.is_staff_user():
                request.session.set_expiry(STAFF_IDLE_TIMEOUT_SECONDS)
            else:
                request.session.set_expiry(CUSTOMER_IDLE_TIMEOUT_SECONDS)
        return response


class RestrictDjangoAdminMiddleware:
    """
    Blocks /admin/ for anyone who isn't an admin user.
    Returns 404 so the route isn't even visible.
    Repeated attempts from same IP get locked out.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/'):
            ip = _client_ip(request)
            lockout_key = f'admin_block_attempts:{ip}'
            attempts = cache.get(lockout_key, 0)

            if attempts >= ADMIN_MAX_ATTEMPTS:
                logger.warning('Blocked /admin/ request from locked-out IP %s', ip)
                raise Http404()

            user = request.user
            if not (user.is_authenticated and user.is_admin_user()):
                cache.set(lockout_key, attempts + 1, ADMIN_LOCKOUT_SECONDS)
                who = user.username if user.is_authenticated else 'anonymous'
                logger.warning(
                    'Blocked /admin/ access attempt from %s (user=%s, path=%s)',
                    ip, who, request.path
                )
                raise Http404()

        return self.get_response(request)