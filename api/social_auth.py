"""
Google sign-in for the mobile app.

The endpoint takes an ID token from Google, verifies it on the server, finds
or creates the matching CustomUser, and returns the SAME payload as
/api/auth/login/ (access, refresh, role, username, full_name, ...), so the
app treats a Google login exactly like a password login.

  POST /api/auth/google/    {"id_token": "..."}

Needs in settings.py:  GOOGLE_CLIENT_ID
and:  pip install google-auth requests
"""
import re

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import CustomUser

from .serializers import CustomTokenObtainPairSerializer


def _unique_username(base):
    base = re.sub(r'[^a-zA-Z0-9_.@+-]', '', base) or 'user'
    base = base[:140]
    username, n = base, 1
    # all_objects so archived accounts' usernames are never reused
    while CustomUser.all_objects.filter(username__iexact=username).exists():
        n += 1
        username = f'{base}{n}'
    return username


def _token_response(request, user):
    """Same JSON shape as LoginView, plus the usual login activity log."""
    user_logged_in.send(sender=user.__class__, request=request._request, user=user)
    refresh = CustomTokenObtainPairSerializer.get_token(user)
    return Response({
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        'role': user.role,
        'username': user.username,
        'full_name': user.get_full_name(),
        'is_staff_role': user.is_staff_user(),
        'is_admin_role': user.is_admin_user(),
    })


def _get_or_create_user(email, first_name, last_name):
    """Returns (user, error_response). Existing accounts with the same email
    are reused; otherwise a new customer account is created."""
    user = CustomUser.all_objects.filter(email__iexact=email).order_by('is_deleted', 'id').first()

    if user is not None:
        if user.is_deleted:
            return None, Response(
                {'detail': 'This account has been removed. Please contact support.'},
                status=status.HTTP_403_FORBIDDEN)
        if not user.is_active:
            # Registered but never confirmed the emailed code: Google has
            # verified the email for us, so let them in.
            if user.email_otps.filter(is_used=False).exists():
                user.is_active = True
                user.save(update_fields=['is_active'])
            else:
                return None, Response(
                    {'detail': 'This account is disabled. Please contact support.'},
                    status=status.HTTP_403_FORBIDDEN)
        return user, None

    user = CustomUser(
        username=_unique_username(email.split('@')[0]),
        email=email,
        first_name=first_name,
        last_name=last_name,
        role='customer',
        is_active=True,   # Google already verified the email: no OTP step
    )
    user.set_unusable_password()
    user.save()
    return user, None


class GoogleLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_scope = 'login'

    def post(self, request):
        token = request.data.get('id_token')
        if not token:
            return Response({'detail': 'Missing id_token.'}, status=status.HTTP_400_BAD_REQUEST)
        if not settings.GOOGLE_CLIENT_ID:
            return Response({'detail': 'Google sign-in is not configured on the server.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token
            info = google_id_token.verify_oauth2_token(
                token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
        except ValueError:
            return Response({'detail': 'Invalid Google token.'}, status=status.HTTP_401_UNAUTHORIZED)

        email = (info.get('email') or '').strip().lower()
        if not email or not info.get('email_verified'):
            return Response({'detail': 'Your Google email is not verified.'},
                            status=status.HTTP_400_BAD_REQUEST)

        user, error = _get_or_create_user(
            email, info.get('given_name', ''), info.get('family_name', ''))
        if error:
            return error
        return _token_response(request, user)