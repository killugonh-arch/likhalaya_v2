from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from orders.models import Order
from orders.shipping import get_shipping_quote, calculate_shipping_fee
from store.models import Category, Product


class ShippingQuoteTests(TestCase):
    def test_carigara_is_free_any_quantity(self):
        self.assertEqual(calculate_shipping_fee(1, 'Leyte', 'Carigara'), Decimal('0'))
        self.assertEqual(calculate_shipping_fee(10, 'Leyte', 'Carigara'), Decimal('0'))
        self.assertTrue(get_shipping_quote(1, 'Leyte', 'Carigara')['free'])

    def test_leyte_fee_grows_with_distance(self):
        barugo = calculate_shipping_fee(1, 'Leyte', 'Barugo')
        tacloban = calculate_shipping_fee(1, 'Leyte', 'Tacloban City')
        baybay = calculate_shipping_fee(1, 'Leyte', 'Baybay')
        self.assertGreater(barugo, 0)
        self.assertLess(barugo, tacloban)
        self.assertLess(tacloban, baybay)

    def test_farther_costs_more(self):
        near = calculate_shipping_fee(1, 'Leyte', 'Barugo')
        mid = calculate_shipping_fee(1, 'Cebu', '')
        far = calculate_shipping_fee(1, 'Ilocos Norte', '')
        self.assertLess(near, mid)
        self.assertLess(mid, far)

    def test_more_items_cost_more_and_cap(self):
        one = calculate_shipping_fee(1, 'Leyte', 'Tacloban')
        three = calculate_shipping_fee(3, 'Leyte', 'Tacloban')
        many = calculate_shipping_fee(100, 'Leyte', 'Tacloban')
        self.assertEqual(three - one, Decimal('20'))
        self.assertEqual(many - one, Decimal('100'))

    def test_unknown_province_uses_fallback(self):
        q = get_shipping_quote(1, 'Nowhere', '')
        self.assertTrue(q['estimated'])
        self.assertIsNone(q['distance_km'])

    def test_ncr_aliases(self):
        a = calculate_shipping_fee(1, 'National Capital Region', 'Quezon City')
        b = calculate_shipping_fee(1, 'Metro Manila', '')
        self.assertEqual(a, b)


class ShippingFlowTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='cust', email='cust@example.com', password='pw12345!',
            phone='09123456789', address='1 Main St', city='Cebu City',
            province='Cebu')
        cat = Category.objects.create(name='Bags')
        self.product = Product.objects.create(
            category=cat, name='Bag', price_min=Decimal('300'), stock=10)
        self.client.force_login(self.user)

    def test_cart_page_shows_location_fee(self):
        self.client.post(reverse('orders:cart_add', args=[self.product.pk]), {'quantity': 2})
        resp = self.client.get(reverse('orders:cart_detail'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['shipping_fee'], get_shipping_quote(2, 'Cebu', 'Cebu City')['fee'])

    def test_cod_order_saves_distance_fee(self):
        self.client.post(reverse('orders:cart_add', args=[self.product.pk]), {'quantity': 2})
        self.client.post(reverse('orders:checkout_select'), {'selected_items': [self.product.pk]})
        self.client.post(reverse('orders:checkout'), {
            'payment_method': 'cod', 'full_name': 'Test', 'email': 'cust@example.com',
            'phone': '09123456789', 'address': '1 Main St', 'city': 'Cebu City',
            'province': 'Cebu', 'zip_code': '6000',
        })
        order = Order.objects.get()
        expected = get_shipping_quote(2, 'Cebu', 'Cebu City')['fee']
        self.assertEqual(order.shipping_fee, expected)
        self.assertEqual(order.total, Decimal('600') + expected)