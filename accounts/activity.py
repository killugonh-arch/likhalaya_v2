"""
Helpers for recording staff/user activity (logins, logouts, and staff actions
taken in the dashboard) into accounts.models.ActivityLog.
"""
import logging

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Client IP for the activity log. Uses the shared trusted-proxy resolver
    so a spoofed X-Forwarded-For header can't forge the address recorded."""
    if not request:
        return None
    from likhalaya_project.rate_limit import get_client_ip as _resolve
    ip = _resolve(request)
    return None if ip == 'unknown' else ip


def _fit(value, max_length):
    """Trim a value to the column's max_length. SQLite ignores varchar limits
    but PostgreSQL (used on Render) raises DataError, which caused a 500."""
    if value is None:
        return ''
    value = str(value)
    if len(value) <= max_length:
        return value
    return value[:max_length - 1] + '…'


def log_activity(request, action, description='', user=None, resource='', resource_label='',
                  previous_value='', new_value='', status='success'):
    """
    Create an ActivityLog entry.

    `user` can be passed explicitly (e.g. from an auth signal where
    request.user may not yet be populated); otherwise it's taken from
    request.user.

    `resource` / `resource_label` identify what was affected (e.g.
    resource='Product', resource_label='Handwoven Basket'). `previous_value`
    / `new_value` capture a before/after snapshot for updates (e.g. an order
    status change). `status` is 'success' or 'failed'.

    Logging must never break the action being logged, so any failure here is
    recorded to the server log instead of raising.
    """
    from .models import ActivityLog

    if user is None:
        user = getattr(request, 'user', None)
        if user is not None and not user.is_authenticated:
            user = None

    try:
        ActivityLog.objects.create(
            user=user,
            username=_fit(getattr(user, 'username', '') or '', 150),
            role=_fit(getattr(user, 'role', '') or '', 20),
            action=_fit(action, 20),
            description=_fit(description, 255),
            resource=_fit(resource, 50),
            resource_label=_fit(resource_label, 255),
            previous_value=_fit(previous_value, 255),
            new_value=_fit(new_value, 255),
            status=_fit(status, 10),
            ip_address=get_client_ip(request),
        )
    except Exception:
        logger.exception('Failed to write activity log entry (%s)', action)