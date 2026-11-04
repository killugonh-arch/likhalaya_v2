from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0014_order_eta_set_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='barangay',
            field=models.CharField(blank=True, max_length=150),
        ),
    ]