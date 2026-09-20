# Generated manually for size-specific product images

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0007_livelihoodvideo'),
    ]

    operations = [
        migrations.AddField(
            model_name='productimage',
            name='size',
            field=models.CharField(
                blank=True,
                choices=[('', 'All sizes (general)'), ('S', 'Small'), ('M', 'Medium'), ('L', 'Large')],
                help_text='Leave blank to show for every size. Set to Small/Medium/Large to show only when that size is picked.',
                max_length=1,
            ),
        ),
        migrations.AddField(
            model_name='productimage',
            name='order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name='productimage',
            options={'ordering': ['order', 'id']},
        ),
    ]