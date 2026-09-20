# Generated manually — adds the GCash account name/number fields shown
# alongside the QR code at checkout (Admin-editable, see dashboard views).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0008_gcash_qr_management'),
    ]

    operations = [
        migrations.AddField(
            model_name='gcashqrcode',
            name='account_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='gcashqrcode',
            name='account_number',
            field=models.CharField(blank=True, max_length=30),
        ),
    ]