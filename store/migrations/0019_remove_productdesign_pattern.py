from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0018_livelihoodvideo_show_on_home'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='productdesign',
            name='pattern',
        ),
    ]