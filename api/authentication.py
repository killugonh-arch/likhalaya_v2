from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class MobileJWTAuthentication(JWTAuthentication):
    """Same as JWTAuthentication, but a Staff account that has not been given
    mobile access is rejected on every API request. This also cuts off a staff
    member whose access is switched off while they are still signed in."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if user.role == 'staff' and not user.mobile_access:
            raise AuthenticationFailed(
                'Your staff account is not enabled for the mobile app.',
                code='mobile_access_denied')
        return user