"""Health checks and alerts (ajna_health_lens/health.py)."""
import datetime
from io import StringIO
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from . import health

ADMINS = [('Ops', 'ops@example.com')]


@override_settings(ADMINS=ADMINS)
class HealthTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_healthy_when_the_worker_beat_recently(self):
        health.worker_heartbeat()
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['ok'], True)
        self.assertIn('no-cache', response['Cache-Control'])

    def test_503_when_the_worker_is_silent(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual((response.json()['database'], response.json()['worker']), (True, False))
        cache.set(health.HEARTBEAT_KEY, (timezone.now() - datetime.timedelta(minutes=20)).isoformat(), None)
        self.assertEqual(self.client.get('/healthz/').status_code, 503)

    def test_stopped_worker_is_emailed_at_most_hourly(self):
        out = StringIO()
        call_command('check_health', stdout=out)
        self.assertIn('background worker (qcluster) looks stopped', out.getvalue())
        self.assertEqual(mail.outbox[0].to, ['ops@example.com'])
        call_command('check_health', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)

    def test_failed_background_jobs_are_reported_once(self):
        from django_q.models import Task

        health.worker_heartbeat()
        Task.objects.create(
            id='a' * 32, name='nightly', func='ajna_health_lens.backups.email_backup', started=timezone.now(),
            stopped=timezone.now(), success=False, result='mysqldump failed: denied',
        )
        problems = health.alert_if_unhealthy()
        self.assertEqual(len(problems), 1)
        self.assertIn('email_backup failed', problems[0])
        self.assertIn('mysqldump failed: denied', mail.outbox[0].body)
        self.assertEqual(health.alert_if_unhealthy(), [])

    def test_all_healthy_sends_nothing(self):
        health.worker_heartbeat()
        out = StringIO()
        call_command('check_health', stdout=out)
        self.assertIn('All healthy.', out.getvalue())
        self.assertEqual(mail.outbox, [])

    def test_database_down_is_reported(self):
        with patch('ajna_health_lens.health.connection.cursor', side_effect=Exception('gone')):
            self.assertEqual(self.client.get('/healthz/').json()['database'], False)

    def test_heartbeat_runs_on_the_worker(self):
        from django_q.models import Schedule

        schedule = Schedule.objects.get(name='worker_heartbeat')
        self.assertEqual((schedule.func, schedule.minutes), ('ajna_health_lens.health.worker_heartbeat', 5))

    def test_deploy_check_warns_without_admins(self):
        from articles.checks import check_admin_emails

        with self.settings(DEBUG=False, ADMINS=[]):
            self.assertEqual([w.id for w in check_admin_emails(None)], ['ajna.W003'])
