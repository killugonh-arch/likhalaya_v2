from django.db import migrations, models


def backfill_size_codes(apps, schema_editor):
    """Older ProductSize rows may have free-text names like "small",
    "Small", "8x10", etc. Map anything recognizable to S/M/L; anything else
    just becomes Small (M/L can be re-added by the admin from the product
    form) so the AlterField below never fails on bad data."""
    ProductSize = apps.get_model('store', 'ProductSize')
    for size in ProductSize.objects.all():
        raw = (size.name or '').strip().lower()
        if raw.startswith('s'):
            code = 'S'
        elif raw.startswith('m'):
            code = 'M'
        elif raw.startswith('l'):
            code = 'L'
        else:
            code = 'S'
        if size.name != code:
            size.name = code
            size.save(update_fields=['name'])


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0016_finalize_variant_schema'),
    ]

    operations = [
        migrations.RunPython(backfill_size_codes, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='productsize',
            name='price',
        ),
        migrations.AlterField(
            model_name='productsize',
            name='name',
            field=models.CharField(
                choices=[('S', 'Small'), ('M', 'Medium'), ('L', 'Large')],
                help_text='Small, Medium, or Large',
                max_length=1,
            ),
        ),
    ]