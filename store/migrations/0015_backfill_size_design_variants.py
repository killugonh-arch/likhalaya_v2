from django.db import migrations


def backfill(apps, schema_editor):
    Product = apps.get_model('store', 'Product')
    ProductSize = apps.get_model('store', 'ProductSize')
    ProductDesign = apps.get_model('store', 'ProductDesign')

    SIZE_CODES = [
        ('S', 'Small', 'price_min', 'stock_s'),
        ('M', 'Medium', 'price_medium', 'stock_m'),
        ('L', 'Large', 'price_max', 'stock_l'),
    ]

    for product in Product.objects.all():
        old_designs = list(ProductDesign.objects.filter(product=product).order_by('order', 'id'))
        if not old_designs:
            continue

        size_objs = {}
        for code, label, price_field, stock_field in SIZE_CODES:
            price = getattr(product, price_field, None)
            # Skip a tier entirely if the product never had that price set
            # (e.g. no Large price means no Large size existed).
            if price is None:
                continue
            # Only create the size if at least one design actually stocks it.
            has_stock_for_size = any(getattr(d, stock_field, 0) for d in old_designs)
            if not has_stock_for_size and code != 'S':
                continue
            size_objs[code] = ProductSize.objects.create(
                product=product,
                name=label,
                price=price,
                is_active=True,
                order={'S': 0, 'M': 1, 'L': 2}[code],
            )

        for d in old_designs:
            for code, label, price_field, stock_field in SIZE_CODES:
                size_obj = size_objs.get(code)
                if not size_obj:
                    continue
                stock_value = getattr(d, stock_field, 0) or 0
                ProductDesign.objects.create(
                    product_size=size_obj,
                    title=d.name or '',
                    color='',
                    pattern='',
                    image=d.image,
                    stock=stock_value,
                    is_active=d.is_active,
                    order=d.order,
                )


def noop_reverse(apps, schema_editor):
    # New ProductSize rows (and the ProductDesign rows created above) are
    # simply left in place on reverse; the old name/product/stock_* fields
    # are restored separately by migration 0016's reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0014_remove_productdesign_name_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
