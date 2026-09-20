from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def backfill_price_medium(apps, schema_editor):
    Product = apps.get_model('store', 'Product')
    for product in Product.objects.filter(price_medium__isnull=True):
        if product.price_max and product.price_max > product.price_min:
            midpoint = (product.price_min + product.price_max) / 2
            product.price_medium = midpoint.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            product.price_medium = product.price_min
        product.save(update_fields=['price_medium'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0003_product_price_medium'),
    ]

    operations = [
        migrations.RunPython(backfill_price_medium, noop_reverse),
    ]