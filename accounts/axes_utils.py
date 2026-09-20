def get_username(request, credentials):
    """Normalize username to lowercase so login attempts are case-insensitive."""
    if credentials:
        username = credentials.get('username')
    else:
        username = request.POST.get('username') if request is not None else None
    if not username:
        return username
    return str(username).strip().lower()