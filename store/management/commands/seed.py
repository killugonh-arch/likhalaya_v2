from django.core.management.base import BaseCommand
from store.models import Category, Product, Personnel
from accounts.models import CustomUser

class Command(BaseCommand):
    help = 'Seed demo data for Likhalaya'

    def handle(self, *args, **kwargs):
        # Admin
        if not CustomUser.objects.filter(username='admin').exists():
            CustomUser.objects.create_superuser('admin', 'admin@likhalaya.com', 'admin1234', role='admin')
            self.stdout.write(self.style.SUCCESS('Admin created: admin / admin1234'))
        self.stdout.write(self.style.SUCCESS('Seed complete!'))
