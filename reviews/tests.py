from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from reviews.models import Review, review_stats
from store.models import Product


class ReviewFlowTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Woven Basket', price_min=100, stock=5)
        self.customer = CustomUser.objects.create_user(
            username='cust', email='cust@example.com', password='pw12345!',
            first_name='Maria', last_name='Santos')
        self.staff = CustomUser.objects.create_user(
            username='staffer', email='staff@example.com', password='pw12345!', role='staff')

    def submit(self, rating, comment=''):
        return self.client.post(reverse('reviews:submit', args=[self.product.slug]),
                                {'rating': rating, 'comment': comment})

    def test_login_required_to_review(self):
        resp = self.submit(5, 'nice')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Review.objects.count(), 0)

    def test_create_then_update_keeps_single_review(self):
        self.client.force_login(self.customer)
        self.submit(4, 'good')
        self.submit(2, 'changed my mind')
        self.assertEqual(Review.objects.count(), 1)
        r = Review.objects.get()
        self.assertEqual((r.rating, r.comment, r.reviewer_name), (2, 'changed my mind', 'Maria S.'))

    def test_invalid_rating_rejected(self):
        self.client.force_login(self.customer)
        self.submit(9, 'x')
        self.submit('', 'x')
        self.assertEqual(Review.objects.count(), 0)

    def test_hidden_review_excluded_from_stats_and_page(self):
        self.client.force_login(self.customer)
        self.submit(5, 'love it')
        self.assertEqual(review_stats(self.product)['total'], 1)
        r = Review.objects.get()
        r.is_visible = False
        r.save()
        self.assertEqual(review_stats(self.product)['total'], 0)
        self.client.logout()
        page = self.client.get(self.product.get_absolute_url())
        self.assertNotContains(page, 'love it')

    def test_product_page_shows_review_and_reply(self):
        self.client.force_login(self.customer)
        self.submit(5, 'Beautiful weave')
        r = Review.objects.get()
        r.staff_reply = 'Thank you!'
        r.save()
        self.client.logout()
        page = self.client.get(self.product.get_absolute_url())
        self.assertContains(page, 'Beautiful weave')
        self.assertContains(page, 'Thank you!')
        self.assertContains(page, 'Maria S.')
        self.assertNotContains(page, 'cust@example.com')

    def test_dashboard_requires_staff(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('reviews:dashboard_list')).status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('reviews:dashboard_list')).status_code, 200)

    def test_staff_toggle_reply_but_only_admin_delete(self):
        review = Review.objects.create(product=self.product, user=self.customer,
                                       reviewer_name='Maria S.', rating=3, comment='ok')
        self.client.force_login(self.staff)
        self.client.post(reverse('reviews:dashboard_toggle', args=[review.pk]))
        review.refresh_from_db()
        self.assertFalse(review.is_visible)
        self.client.post(reverse('reviews:dashboard_reply', args=[review.pk]), {'staff_reply': 'Sorry!'})
        review.refresh_from_db()
        self.assertEqual(review.staff_reply, 'Sorry!')
        self.assertEqual(review.replied_by, self.staff)
        self.client.post(reverse('reviews:dashboard_delete', args=[review.pk]))
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())  # staff can't delete
        admin = CustomUser.objects.create_user(username='adm', email='a@example.com',
                                               password='pw12345!', role='admin')
        self.client.force_login(admin)
        self.client.post(reverse('reviews:dashboard_delete', args=[review.pk]))
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())

    def test_dashboard_filters(self):
        Review.objects.create(product=self.product, user=self.customer, reviewer_name='Maria S.', rating=5, comment='zzmarker comment')
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('reviews:dashboard_list'), {'rating': '5', 'status': 'unreplied', 'q': 'zzmarker'})
        self.assertContains(resp, 'zzmarker comment')
        resp = self.client.get(reverse('reviews:dashboard_list'), {'rating': '1'})
        self.assertNotContains(resp, 'zzmarker comment')

    def test_customer_can_delete_own_only(self):
        other = CustomUser.objects.create_user(username='o', email='o@example.com', password='pw12345!')
        mine = Review.objects.create(product=self.product, user=self.customer, reviewer_name='M', rating=4)
        theirs = Review.objects.create(product=self.product, user=other, reviewer_name='O', rating=1)
        self.client.force_login(self.customer)
        self.client.post(reverse('reviews:delete_mine', args=[theirs.pk]))
        self.assertTrue(Review.objects.filter(pk=theirs.pk).exists())
        self.client.post(reverse('reviews:delete_mine', args=[mine.pk]))
        self.assertFalse(Review.objects.filter(pk=mine.pk).exists())



class ProductCardRatingTests(TestCase):
    def test_shop_home_category_cards_show_rating(self):
        from store.models import Category
        cat = Category.objects.create(name='Paintings')
        p = Product.objects.create(name='Sunset Canvas', price_min=500, stock=3, category=cat)
        u = CustomUser.objects.create_user(username='u', email='u@example.com', password='pw12345!')
        Review.objects.create(product=p, user=u, reviewer_name='U', rating=4, comment='nice')
        for url in (reverse('store:shop'), reverse('store:home'), cat.get_absolute_url()):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, '(1)', msg_prefix=url)
            self.assertContains(resp, '4.0', msg_prefix=url)