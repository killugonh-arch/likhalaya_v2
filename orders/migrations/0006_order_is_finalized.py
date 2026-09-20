from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0005_order_previous_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='is_finalized',
            field=models.BooleanField(default=True),
        ),
    ]