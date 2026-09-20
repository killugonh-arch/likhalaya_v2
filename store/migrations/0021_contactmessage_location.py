from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0020_contactmessage_concern_type_contactmessage_customer_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='contactmessage',
            name='location',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]