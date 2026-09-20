from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0008_productimage_size_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='gcash_qr_code',
            field=models.ImageField(
                blank=True, null=True, upload_to='products/gcash_qr/',
                help_text="GCash QR code for this product. Set on creation; only an Admin can change it afterward."
            ),
        ),
    ]