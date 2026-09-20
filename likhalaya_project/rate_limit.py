"""Cache-based rate limiting helpers used across views."""
from django.core.cache import cache
import functools


def get_client_ip(request):
    """Get client IP using axes resolver, fallback to REMOTE_ADDR."""
    try:
        from axes.helpers import get_client_ip_address
        ip = get_client_ip_address(request)
    except Exception:
        ip = None
    return ip or request.META.get('REMOTE_ADDR', 'unknown')


def check_cooldown(key, cooldown_seconds):
    """Returns True if allowed; False if still in cooldown."""
    if cache.get(key):
        return False
    cache.set(key, True, cooldown_seconds)
    return True


def check_hourly_limit(key, max_per_hour):
    """Returns True if under hourly cap and increments counter."""
    count = cache.get(key, 0)
    if count >= max_per_hour:
        return False
    cache.set(key, count + 1, 60 * 60)
    return True


def throttle(key_func, max_per_hour, response_factory=None):
    """View decorator to cap calls per hour per cache key."""
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped(request, *args, **kwargs):
            key = key_func(request)
            if not check_hourly_limit(key, max_per_hour):
                if response_factory:
                    return response_factory(request)
                from django.http import HttpResponse
                return HttpResponse('Too many requests. Please try again later.', status=429)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator