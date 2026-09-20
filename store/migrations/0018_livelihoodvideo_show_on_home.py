from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0017_size_price_removed'),
    ]

    operations = [
        migrations.AddField(
            model_name='livelihoodvideo',
            name='show_on_home',
            field=models.BooleanField(
                default=False,
                help_text="Feature this video on the Home page (max 2 shown there). "
                          "The About page always shows every active video."
            ),
        ),
    ]