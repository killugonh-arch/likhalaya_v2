from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from orders.models import Notification, Order


class OrderEtaTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username='adm', email='adm@example.com', password='pw12345!', role='admin')
        self.customer = CustomUser.objects.create_user(
            username='cust', email='cust@example.com', password='pw12345!')
        self.order = Order.objects.create(
            user=self.customer, full_name='Maria Santos', email='cust@example.com',
            phone='09123456789', address='1 Main St', city='Carigara',
            province='Leyte', zip_code='6538')
        self.client.force_login(self.admin)

    def start(self, lo, hi):
        return self.client.post(
            reverse('dashboard:order_start_processing', args=[self.order.pk]),
            {'eta_days_min': lo, 'eta_days_max': hi})

    def test_eta_display_formats(self):
        o = self.order
        self.assertEqual(o.eta_display, '')
        o.eta_days_min, o.eta_days_max = 2, 3
        self.assertEqual(o.eta_display, '2\u20133 days')
        o.eta_days_min, o.eta_days_max = 1, 1
        self.assertEqual(o.eta_display, '1 day')
        o.eta_days_min, o.eta_days_max = 5, 5
        self.assertEqual(o.eta_display, '5 days')

    def test_start_processing_requires_eta(self):
        self.start('', '')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')

    def test_start_processing_with_eta_sets_status_and_notifies(self):
        self.start(2, 3)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'processing')
        self.assertEqual((self.order.eta_days_min, self.order.eta_days_max), (2, 3))
        note = Notification.objects.get(order=self.order)
        self.assertIn('2\u20133 days', note.message)
        self.assertEqual(note.user, self.customer)

    def test_bad_eta_does_not_change_status(self):
        for lo, hi in [(5, 2), (0, 3), (2, 99), (2, ''), ('a', 3)]:
            self.start(lo, hi)
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, 'pending', (lo, hi))
            self.assertIsNone(self.order.eta_days_min)

    def test_update_eta_while_processing_and_clear(self):
        self.start(2, 3)
        self.client.post(reverse('dashboard:order_set_eta', args=[self.order.pk]),
                         {'eta_days_min': 4, 'eta_days_max': 5})
        self.order.refresh_from_db()
        self.assertEqual(self.order.eta_display, '4\u20135 days')
        self.assertEqual(Notification.objects.filter(order=self.order).count(), 2)
        self.client.post(reverse('dashboard:order_set_eta', args=[self.order.pk]),
                         {'eta_days_min': '', 'eta_days_max': ''})
        self.order.refresh_from_db()
        self.assertEqual(self.order.eta_display, '')

    def test_cannot_change_eta_after_delivered(self):
        self.start(2, 3)
        Order.objects.filter(pk=self.order.pk).update(status='delivered')
        self.client.post(reverse('dashboard:order_set_eta', args=[self.order.pk]),
                         {'eta_days_min': 9, 'eta_days_max': 9})
        self.order.refresh_from_db()
        self.assertEqual(self.order.eta_display, '2\u20133 days')

    def test_customer_sees_eta_only_while_in_progress(self):
        self.start(2, 3)
        self.client.force_login(self.customer)
        url = reverse('orders:order_detail', args=[self.order.pk])
        self.assertContains(self.client.get(url), 'Estimated delivery')
        self.assertContains(self.client.get(url), '2\u20133 days')
        Order.objects.filter(pk=self.order.pk).update(status='delivered')
        self.assertNotContains(self.client.get(url), 'Estimated delivery')

    def test_dashboard_forms_render_per_status(self):
        url = reverse('dashboard:order_detail', args=[self.order.pk])
        self.assertContains(self.client.get(url), 'name="eta_days_min"')
        self.start(2, 3)
        resp = self.client.get(url)
        self.assertContains(resp, reverse('dashboard:order_set_eta', args=[self.order.pk]))
        self.assertContains(resp, 'value="2"')

    def test_customer_cannot_use_admin_eta_endpoint(self):
        self.client.force_login(self.customer)
        resp = self.client.post(reverse('dashboard:order_set_eta', args=[self.order.pk]),
                                {'eta_days_min': 1, 'eta_days_max': 1})
        self.assertEqual(resp.status_code, 302)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.eta_days_min)

    def test_timeline_shows_eta_under_processing_step(self):
        url = reverse('dashboard:order_detail', args=[self.order.pk])
        self.assertNotContains(self.client.get(url), 'od-tl-eta"')
        self.start(2, 3)
        resp = self.client.get(url)
        self.assertContains(resp, 'class="od-tl-eta"')
        self.assertContains(resp, 'Estimated delivery: <strong>2\u20133 days</strong>')
        Order.objects.filter(pk=self.order.pk).update(status='delivered')
        self.assertNotContains(self.client.get(url), 'class="od-tl-eta"')