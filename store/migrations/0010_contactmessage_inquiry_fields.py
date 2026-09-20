from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0009_product_gcash_qr_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='contactmessage',
            name='inquiry_type',
            field=models.CharField(
                choices=[
                    ('general', 'General Inquiry'),
                    ('product_inquiry', 'Product Inquiry'),
                    ('product_request', 'Product Request'),
                    ('custom_order', 'Custom Order Request'),
                    ('bulk_order', 'Bulk / Wholesale Order'),
                    ('donate_materials', 'Donation of Raw Materials'),
                    ('partnership', 'Partnership or Collaboration'),
                    ('feedback', 'Feedback or Suggestions'),
                    ('other', 'Other Concerns'),
                ],
                default='general',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='phone',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='item_name',
            field=models.CharField(
                blank=True, max_length=200,
                help_text='Product name/type, custom order product type, or materials to donate.',
            ),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='quantity',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='customization_request',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='preferred_materials',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='target_budget',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='preferred_date',
            field=models.DateField(
                blank=True, null=True,
                help_text='Needed-by date (custom order) or preferred donation date.',
            ),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='reference_image',
            field=models.ImageField(blank=True, null=True, upload_to='contact_references/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='organization_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='materials_condition',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='partnership_type',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='feedback_type',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='related_product',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='additional_details',
            field=models.TextField(blank=True),
        ),
    ]