import logging

from django.core.cache import cache
from django.http import Http404

logger = logging.getLogger('security')

ADMIN_MAX_ATTEMPTS = 5
ADMIN_LOCKOUT_SECONDS = 15 * 60

# only applies to staff/admin, not regular customers
STAFF_IDLE_TIMEOUT_SECONDS = 30 * 60


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


class StaffIdleTimeoutMiddleware:
    """Logs out staff after 30 min idle. Resets on each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and user.is_staff_user():
            request.session.set_expiry(STAFF_IDLE_TIMEOUT_SECONDS)
        return self.get_response(request)


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