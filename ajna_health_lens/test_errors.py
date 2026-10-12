"""Error pages (404, 500, expired form) and the alerts behind them."""
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import path


def broken_view(request):
    raise RuntimeError('Something broke')


urlpatterns = [path('boom/', broken_view)]

ADMINS = [('Ops', 'ops@example.com')]


class NotFoundPageTests(TestCase):
    def test_site_styled_404_suggests_a_search(self):
        response = self.client.get('/articles/malaria-vaccine-trial/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'We can’t find that page', status_code=404)
        self.assertContains(response, 'value="malaria vaccine trial"', status_code=404)
        self.assertContains(response, 'noindex', status_code=404)

    @override_settings(ADMINS=ADMINS, MANAGERS=ADMINS)
    def test_a_broken_link_on_our_own_site_is_emailed(self):
        self.client.get('/articles/gone-story/', HTTP_REFERER='http://testserver/articles/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/articles/gone-story/', mail.outbox[0].subject + mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ['ops@example.com'])

    @override_settings(ADMINS=ADMINS, MANAGERS=ADMINS)
    def test_outside_links_and_bot_probes_are_not_emailed(self):
        self.client.get('/old-page/', HTTP_REFERER='https://elsewhere.example/', HTTP_USER_AGENT='Mozilla/5.0')
        self.client.get('/wp-login.php', HTTP_REFERER='http://testserver/', HTTP_USER_AGENT='Mozilla/5.0')
        self.client.get('/no-referer/')
        self.assertEqual(mail.outbox, [])


@override_settings(ROOT_URLCONF='ajna_health_lens.test_errors', ADMINS=ADMINS, MANAGERS=ADMINS)
class ServerErrorTests(TestCase):
    def test_500_page_is_standalone_and_admins_are_emailed(self):
        client = Client(raise_request_exception=False)
        response = client.get('/boom/')
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, 'Something went wrong on our side', status_code=500)
        self.assertContains(response, 'हाम्रो तर्फबाट', status_code=500)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('RuntimeError', mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ['ops@example.com'])


class ExpiredFormTests(TestCase):
    def test_missing_security_token_explains_itself(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post('/newsletter/subscribe/', {'email': 'x@example.com'})
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Please try that again', status_code=403)


class SecurityHeaderTests(TestCase):
    def test_every_page_has_a_content_security_policy(self):
        response = self.client.get('/')
        policy = response['Content-Security-Policy']
        for part in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'", 'https://www.youtube-nocookie.com',
                     'https://www.googletagmanager.com', 'report-uri /csp-report/'):
            self.assertIn(part, policy)
        self.assertIn('camera=()', response['Permissions-Policy'])

    def test_violation_reports_are_logged_not_emailed(self):
        import json

        with self.assertLogs('ajna_health_lens.error_views', level='WARNING') as logs:
            response = Client(enforce_csrf_checks=True).post(
                '/csp-report/', json.dumps({'csp-report': {'blocked-uri': 'https://evil.example/x.js',
                                                          'violated-directive': 'script-src'}}),
                content_type='application/csp-report',
            )
        self.assertEqual(response.status_code, 204)
        self.assertIn('https://evil.example/x.js', logs.output[0])
        self.assertEqual(mail.outbox, [])
