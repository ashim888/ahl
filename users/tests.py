from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User

# django_ratelimit buckets requests into a fixed time window (see
# django_ratelimit.core._get_window) — a slow burst of requests risks
# flakily straddling a window reset if it happens to run near a boundary.
# Django's real password hasher (PBKDF2) is deliberately slow, so a 15+
# request login/register burst could take long enough for that to matter;
# swapping in a fast test-only hasher (Django's own documented pattern for
# exactly this) keeps the whole burst well under a second, not a fix for
# time itself. (freeze_time was tried and rejected — it hung the test
# runner, apparently confusing the MySQL driver's connection handling.)
FAST_PASSWORD_HASHERS = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


@FAST_PASSWORD_HASHERS
class LoginRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_normal_login_attempts_are_not_blocked(self):
        for _ in range(3):
            response = self.client.post(reverse('users:login'), {'username': 'nobody@example.com', 'password': 'wrong'})
            self.assertEqual(response.status_code, 200)  # re-renders the form with an error, not blocked

    def test_excessive_login_attempts_are_rate_limited(self):
        # Limit is 15/m (users/views.py EmailLoginView) — the 16th POST in
        # the same window should be blocked rather than processed.
        for _ in range(15):
            self.client.post(reverse('users:login'), {'username': 'nobody@example.com', 'password': 'wrong'})
        response = self.client.post(reverse('users:login'), {'username': 'nobody@example.com', 'password': 'wrong'})
        self.assertEqual(response.status_code, 403)


@FAST_PASSWORD_HASHERS
class RegisterRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_excessive_registration_attempts_are_rate_limited(self):
        # Limit is 10/h (users/views.py RegisterView).
        for i in range(10):
            self.client.post(reverse('users:register'), {'email': f'spam{i}@example.com'})
        response = self.client.post(reverse('users:register'), {'email': 'spam-overflow@example.com'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email='spam-overflow@example.com').exists())
