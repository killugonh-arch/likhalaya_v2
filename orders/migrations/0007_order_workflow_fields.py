import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('orders', '0006_order_is_finalized'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='assigned_courier',
            field=models.ForeignKey(
                blank=True, null=True,
                limit_choices_to={'role': 'courier'},
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='courier_orders',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='pickup_proof',
            field=models.ImageField(blank=True, null=True, upload_to='pickup_proofs/'),
        ),
        migrations.AddField(
            model_name='order',
            name='pickup_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_proof',
            field=models.ImageField(blank=True, null=True, upload_to='delivery_proofs/'),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]