from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .activity import log_activity


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    log_activity(request, 'login', description='Signed in', user=user,
                 resource='Session', resource_label=getattr(user, 'username', ''),
                 status='success')


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    # user can be None if the session had already expired
    if user is not None:
        log_activity(request, 'logout', description='Signed out', user=user,
                     resource='Session', resource_label=getattr(user, 'username', ''),
                     status='success')


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request=None, **kwargs):
    attempted_username = credentials.get('username', '') if credentials else ''
    from .models import ActivityLog
    from .activity import get_client_ip
    ActivityLog.objects.create(
        user=None,
        username=attempted_username,
        role='',
        action='login_failed',
        description='Failed login attempt',
        resource='Session',
        resource_label=attempted_username,
        status='failed',
        ip_address=get_client_ip(request),
    )