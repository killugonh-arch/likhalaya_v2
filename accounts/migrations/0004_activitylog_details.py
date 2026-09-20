from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_activitylog'),
    ]

    operations = [
        migrations.AddField(
            model_name='activitylog',
            name='resource',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='activitylog',
            name='resource_label',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='activitylog',
            name='previous_value',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='activitylog',
            name='new_value',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='activitylog',
            name='status',
            field=models.CharField(choices=[('success', 'Success'), ('failed', 'Failed')], default='success', max_length=10),
        ),
    ]