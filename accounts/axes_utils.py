def get_username(request, credentials):
    """Normalize username to lowercase so login attempts are case-insensitive."""
    if credentials:
        username = credentials.get('username')
    else:
        username = request.POST.get('username') if request is not None else None
    if not username:
        return username
    return str(username).strip().lower()


def is_exempt_login(login_name):
    """True if this username/email belongs to an account listed in
    settings.AXES_EXEMPT_LOGINS (matched by its email address)."""
    from django.conf import settings
    from accounts.models import CustomUser

    exempt = {str(e).strip().lower() for e in getattr(settings, 'AXES_EXEMPT_LOGINS', [])}
    name = str(login_name or '').strip().lower()
    if not exempt or not name:
        return False
    if name in exempt:
        return True
    user = CustomUser.all_objects.filter(username__iexact=name).only('email').first()
    return bool(user and (user.email or '').strip().lower() in exempt)


def axes_whitelist(request, credentials):
    """django-axes hook (AXES_WHITELIST_CALLABLE): exempt accounts are never
    locked out by failed-attempt tracking."""
    return is_exempt_login(get_username(request, credentials))