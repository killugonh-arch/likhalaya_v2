import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('orders', '0007_order_workflow_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='GCashQRCode',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='gcash_qr/')),
                ('status', models.CharField(
                    choices=[
                        ('pending_confirm', 'Pending Staff Confirmation'),
                        ('active_locked', 'Active & Locked'),
                        ('removal_pending', 'Removal Request Pending'),
                        ('removal_approved', 'Removal Approved'),
                        ('removal_rejected', 'Removal Rejected'),
                        ('inactive', 'Inactive'),
                    ],
                    default='active_locked', max_length=20,
                )),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deactivated_at', models.DateTimeField(blank=True, null=True)),
                ('uploaded_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='uploaded_qr_codes', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='GCashQRRemovalRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.CharField(
                    choices=[
                        ('incorrect', 'QR code was uploaded incorrectly'),
                        ('outdated', 'QR code is outdated'),
                        ('damaged', 'QR code is damaged/unreadable'),
                        ('wrong_account', 'Wrong GCash account'),
                        ('other', 'Other reason'),
                    ],
                    default='other', max_length=20,
                )),
                ('explanation', models.TextField(blank=True)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending Admin Approval'),
                        ('approved', 'Approved'),
                        ('rejected', 'Rejected'),
                    ],
                    default='pending', max_length=20,
                )),
                ('decision_reason', models.TextField(blank=True)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now)),
                ('decided_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='qr_removal_decisions', to=settings.AUTH_USER_MODEL,
                )),
                ('requested_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='qr_removal_requests', to=settings.AUTH_USER_MODEL,
                )),
                ('qr_code', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='removal_requests', to='orders.gcashqrcode',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
    