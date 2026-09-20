from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0015_backfill_size_design_variants'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='productdesign',
            name='name',
        ),
        migrations.RemoveField(
            model_name='productdesign',
            name='product',
        ),
        migrations.RemoveField(
            model_name='productdesign',
            name='stock_l',
        ),
        migrations.RemoveField(
            model_name='productdesign',
            name='stock_m',
        ),
        migrations.RemoveField(
            model_name='productdesign',
            name='stock_s',
        ),
    ]
