from django.test import RequestFactory, TestCase
from django.contrib.auth import get_user_model

from dashboard.context_processors import dashboard_notifications
from orders.models import Order
from store.models import ContactMessage


class DashboardNotificationsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff_user = get_user_model().objects.create_user(
            username='staffuser',
            password='secret123',
            role='staff',
        )
        self.customer_user = get_user_model().objects.create_user(
            username='customer',
            password='secret123',
            role='customer',
        )
        Order.objects.create(
            full_name='Jane Doe',
            email='jane@example.com',
            phone='09171234567',
            address='123 Main Street',
            city='Carigara',
            province='Leyte',
            zip_code='6519',
            status='pending',
            total=150,
        )
        Order.objects.create(
            full_name='John Doe',
            email='john@example.com',
            phone='09181234567',
            address='456 Main Street',
            city='Carigara',
            province='Leyte',
            zip_code='6519',
            status='confirmed',
            total=250,
        )

    def test_staff_user_sees_pending_orders_count(self):
        request = self.factory.get('/')
        request.user = self.staff_user

        context = dashboard_notifications(request)

        self.assertEqual(context['new_orders_count'], 1)

    def test_customer_user_does_not_see_notification_count(self):
        request = self.factory.get('/')
        request.user = self.customer_user

        context = dashboard_notifications(request)

        self.assertEqual(context['new_orders_count'], 0)

    def test_staff_user_sees_unread_messages_count(self):
        ContactMessage.objects.create(
            name='Alice',
            email='alice@example.com',
            subject='hello',
            message='Need help',
            is_read=False,
        )
        request = self.factory.get('/')
        request.user = self.staff_user

        context = dashboard_notifications(request)

        self.assertEqual(context['new_messages_count'], 1)
