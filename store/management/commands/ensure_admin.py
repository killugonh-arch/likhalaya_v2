import os

from django.core.management.base import BaseCommand

from accounts.models import CustomUser


class Command(BaseCommand):
    help = (
        "Create (or repair) the admin account from the ADMIN_EMAIL and "
        "ADMIN_PASSWORD environment variables. Safe to run on every deploy. "
        "An existing account's password is only changed when "
        "ADMIN_RESET_PASSWORD=1 is set."
    )

    def handle(self, *args, **options):
        email = (os.environ.get('ADMIN_EMAIL') or '').strip().lower()
        password = os.environ.get('ADMIN_PASSWORD') or ''
        if not email or not password:
            self.stdout.write('ensure_admin: ADMIN_EMAIL / ADMIN_PASSWORD not set, skipping.')
            return

        user = CustomUser.all_objects.filter(email__iexact=email).first()
        if user is None:
            base = email.split('@')[0] or 'admin'
            username, n = base, 1
            while CustomUser.all_objects.filter(username=username).exists():
                n += 1
                username = f'{base}{n}'
            user = CustomUser(username=username, email=email)
            user.set_password(password)
            created = True
        else:
            created = False
            if os.environ.get('ADMIN_RESET_PASSWORD') == '1':
                user.set_password(password)

        user.role = 'admin'  # save() also sets is_staff / is_superuser
        user.is_active = True
        user.is_deleted = False
        user.save()
        self.stdout.write(self.style.SUCCESS(
            f"ensure_admin: admin account {'created' if created else 'updated'}: {user.email}"
        ))