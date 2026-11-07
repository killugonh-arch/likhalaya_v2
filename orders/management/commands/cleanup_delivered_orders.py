from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from orders.models import Order

PROOF_FIELDS = ('payment_proof', 'pickup_proof', 'delivery_proof')


class Command(BaseCommand):
    help = ("Delete the proof photos (payment / pickup / delivery) of orders "
            "delivered more than N days ago. The orders themselves are kept, "
            "so reports and totals are not affected.")

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=60,
                            help='Age in days after delivery (default 60 = 2 months).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Only show what would be deleted.')

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts['days'])
        has_file = Q()
        for f in PROOF_FIELDS:
            has_file |= (~Q(**{f: ''}) & Q(**{f + '__isnull': False}))

        orders = (Order.objects.filter(status='delivered')
                  .annotate(done_at=Coalesce('delivery_confirmed_at', 'updated_at'))
                  .filter(done_at__lt=cutoff)
                  .filter(has_file))

        orders_done = files_done = 0
        for order in orders:
            changed = []
            for f in PROOF_FIELDS:
                field = getattr(order, f)
                if field:
                    files_done += 1
                    if not opts['dry_run']:
                        field.delete(save=False)   # removes the file from storage
                    changed.append(f)
            if changed and not opts['dry_run']:
                order.save(update_fields=changed)
            orders_done += 1

        verb = 'Would clean' if opts['dry_run'] else 'Cleaned'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {files_done} photo(s) from {orders_done} delivered order(s) '
            f'older than {opts["days"]} days.'))