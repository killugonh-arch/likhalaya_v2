from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0015_order_barangay'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShippingSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('per_extra_item', models.DecimalField(decimal_places=2, default=10, max_digits=8)),
                ('max_item_surcharge', models.DecimalField(decimal_places=2, default=100, max_digits=8)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='ShippingRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('province', models.CharField(blank=True, max_length=100)),
                ('city', models.CharField(blank=True, max_length=100)),
                ('barangay', models.CharField(blank=True, max_length=150)),
                ('base_fee', models.DecimalField(decimal_places=2, max_digits=8)),
                ('per_extra_item', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('max_item_surcharge', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['province', 'city', 'barangay'],
            },
        ),
    ]