import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0009_migration'),
        ('store', '0012_productdesign_per_size_stock'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='design',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='order_items', to='store.productdesign',
            ),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='design_name',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
