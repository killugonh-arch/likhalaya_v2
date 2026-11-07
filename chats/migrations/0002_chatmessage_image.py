from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='chat_images/%Y/%m/'),
        ),
        # Keeps the migration state in step with the model: a message can be
        # just an image, so the text may be empty.
        migrations.AlterField(
            model_name='chatmessage',
            name='body',
            field=models.TextField(blank=True, default='', max_length=2000),
        ),
    ]