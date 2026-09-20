from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyPeriod',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.IntegerField()),
                ('month', models.IntegerField()),
                ('status', models.CharField(choices=[('open', 'Open'), ('finalized', 'Finalized')], default='open', max_length=10)),
                ('finalized_at', models.DateTimeField(blank=True, null=True)),
                ('reopened_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('locked_product_income', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('locked_shipping_income', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('locked_approved_expenses', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('locked_net_product_income', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('locked_pdl_percentage', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('locked_pdl_share_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('finalized_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='finalized_periods', to=settings.AUTH_USER_MODEL)),
                ('reopened_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reopened_periods', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-year', '-month'],
            },
        ),
        migrations.AddConstraint(
            model_name='monthlyperiod',
            constraint=models.UniqueConstraint(fields=('year', 'month'), name='unique_monthly_period'),
        ),
        migrations.CreateModel(
            name='PDLAllocationRule',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('percentage', models.DecimalField(decimal_places=2, max_digits=5)),
                ('effective_from', models.DateField()),
                ('set_at', models.DateTimeField(auto_now_add=True)),
                ('notes', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('set_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pdl_rules_set', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-effective_from', '-set_at'],
            },
        ),
        migrations.CreateModel(
            name='Expense',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.CharField(max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('category', models.CharField(choices=[('materials', 'Materials'), ('utilities', 'Utilities'), ('wages', 'Wages'), ('logistics', 'Logistics'), ('other', 'Other')], default='other', max_length=20)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('is_approved', models.BooleanField(default=False)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('added_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='expenses_added', to=settings.AUTH_USER_MODEL)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='expenses_approved', to=settings.AUTH_USER_MODEL)),
                ('period', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expenses', to='dashboard.monthlyperiod')),
            ],
            options={
                'ordering': ['-added_at'],
            },
        ),
    ]
