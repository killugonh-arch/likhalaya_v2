from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0011_productdesign'),
    ]

    operations = [
        migrations.AddField(
            model_name='productdesign',
            name='stock_s',
            field=models.PositiveIntegerField(default=0, verbose_name='Small stock'),
        ),
        migrations.AddField(
            model_name='productdesign',
            name='stock_m',
            field=models.PositiveIntegerField(default=0, verbose_name='Medium stock'),
        ),
        migrations.AddField(
            model_name='productdesign',
            name='stock_l',
            field=models.PositiveIntegerField(default=0, verbose_name='Large stock'),
        ),
    ]
