from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

GOOD_PASSWORD = 'Correct-Horse-9!'


class LoginLockoutTests(TestCase):
    """django-axes brute-force protection on the web login form."""

    def setUp(self):
        self.url = reverse('accounts:login')
        self.alice = User.objects.create_user(
            username='alice@example.com', email='alice@example.com', password=GOOD_PASSWORD)
        self.bob = User.objects.create_user(
            username='bob@example.com', email='bob@example.com', password=GOOD_PASSWORD)

    def _login(self, email, password, **extra):
        return self.client.post(self.url, {'username': email, 'password': password}, **extra)

    def _fail(self, email, times):
        for _ in range(times):
            self._login(email, 'wrong-password')

    # ── Guard 1: axes locks a single account after 5 failures ──

    def test_correct_password_is_rejected_once_locked(self):
        self._fail('alice@example.com', settings.AXES_FAILURE_LIMIT + 1)
        resp = self._login('alice@example.com', GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_changing_username_case_does_not_reset_the_counter(self):
        self._fail('Alice@Example.com', settings.AXES_FAILURE_LIMIT + 1)
        resp = self._login('alice@example.com', GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 429)

    def test_spoofed_x_forwarded_for_does_not_dodge_the_lockout(self):
        self._fail('alice@example.com', settings.AXES_FAILURE_LIMIT + 1)
        resp = self._login('alice@example.com', GOOD_PASSWORD,
                           HTTP_X_FORWARDED_FOR='203.0.113.77')
        self.assertEqual(resp.status_code, 429)

    def test_locking_one_account_does_not_lock_others(self):
        self._fail('alice@example.com', settings.AXES_FAILURE_LIMIT + 1)
        resp = self._login('bob@example.com', GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 302)  # logged in, redirected
        self.assertIn('_auth_user_id', self.client.session)

    def test_successful_login_resets_the_failure_counter(self):
        below_limit = settings.AXES_FAILURE_LIMIT - 2
        self._fail('alice@example.com', below_limit)
        self.assertEqual(self._login('alice@example.com', GOOD_PASSWORD).status_code, 302)
        self.client.logout()
        self._fail('alice@example.com', below_limit)
        self.assertEqual(self._login('alice@example.com', GOOD_PASSWORD).status_code, 302)

    # ── Guard 2: spray-attack / many-accounts-one-IP ──
    #
    # Thresholds (from views.py):
    #   First account from this IP : 5 failures before it "counts"
    #   Every later account         : 3 failures before it "counts"
    #   IP block fires when         : 3 accounts have crossed their threshold
    #
    # Your exact scenario:
    #   A × 5  →  A is axes-locked AND A counts (5 >= 5, it's the first)
    #   B × 3  →  B counts           (3 >= 3, not the first)
    #   C × 3  →  C counts → IP blocked (3 accounts over threshold)

    def test_your_scenario_a5_b3_c3_blocks_ip(self):
        """5 wrong on A, 3 wrong on B, 3 wrong on C → IP blocked."""
        self._fail('a@example.com', 5)   # axes also locks A
        self._fail('b@example.com', 3)
        self._fail('c@example.com', 3)
        # Even a correct password on a clean account is refused
        resp = self._login('alice@example.com', GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_first_account_needs_5_fails_not_3(self):
        """4 wrong on A (below first-account threshold) then 3+3 on B and C
        → only 2 accounts over threshold → no IP block."""
        self._fail('a@example.com', 4)   # one short of 5 → doesn't count yet
        self._fail('b@example.com', 3)
        self._fail('c@example.com', 3)
        resp = self._login('alice@example.com', GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_later_accounts_need_3_fails_not_1(self):
        """5 wrong on A (first, counts), then only 2 wrong each on B and C
        → B and C haven't crossed their threshold of 3 → no IP block."""
        self._fail('a@example.com', 5)
        self._fail('b@example.com', 2)   # one short of 3 → doesn't count yet
        self._fail('c@example.com', 2)
        resp = self._login('alice@example.com', GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_two_accounts_over_threshold_not_enough_to_block(self):
        """A at 5 + B at 3 = 2 accounts over threshold → no IP block yet."""
        self._fail('a@example.com', 5)
        self._fail('b@example.com', 3)
        resp = self._login('alice@example.com', GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_retrying_one_account_does_not_count_as_multiple_accounts(self):
        """10 wrong on A (still 1 account) → not enough to trigger IP block."""
        self._fail('a@example.com', 10)
        resp = self._login('alice@example.com', GOOD_PASSWORD)
        # Alice's IP is fine; alice herself isn't rate-limited here
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_successful_login_clears_that_account_from_ip_counter(self):
        """5 wrong on A (counts), right password on B (clears B from dict),
        then 3 wrong on C → still only A counts → no IP block."""
        self._fail('a@example.com', 5)
        self.assertEqual(
            self._login('bob@example.com', GOOD_PASSWORD).status_code, 302
        )
        self.client.logout()
        self._fail('c@example.com', 3)
        resp = self._login('alice@example.com', GOOD_PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_retrying_one_account_does_not_trigger_the_ip_block(self):
        """Guard-1-era test kept for regression: 4 wrong on one account
        (below axes limit, below first-account threshold of 5) → login ok."""
        self._fail('alice@example.com', settings.AXES_FAILURE_LIMIT - 1)
        self.assertEqual(self._login('alice@example.com', GOOD_PASSWORD).status_code, 302)