from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_emailotp'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(
                choices=[
                    ('customer', 'Customer'),
                    ('staff', 'Staff'),
                    ('coordinator', 'PDL Coordinator'),
                    ('courier', 'Delivery Courier'),
                    ('admin', 'Administrator'),
                ],
                default='customer',
                max_length=20,
            ),
        ),
    ]