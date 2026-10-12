"""Is the site healthy? Used three ways:

- /healthz/ — for an outside uptime monitor (e.g. UptimeRobot): 200 when the
  database, cache and background worker are fine, 503 otherwise;
- `python manage.py check_health` — run from the server's cron every 15
  minutes; emails ADMINS when the background worker has stopped or a
  background job failed (the worker can't report its own death);
- worker_heartbeat — a qcluster job every 5 minutes that proves the worker
  is alive (admin_custom/migrations/0004_worker_heartbeat_schedule).

Payments being confirmed, renewal reminders, the nightly backup and the
privacy clean-up all run on that worker — if it stops, nothing else says so.
"""
import datetime
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import mail_admins
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = 'health:worker-heartbeat'
LAST_FAILURE_CHECK_KEY = 'health:last-failure-check'
ALERT_THROTTLE_KEY = 'health:worker-alert-sent'


def worker_heartbeat() -> str:
    """Runs on the qcluster worker every few minutes."""
    now = timezone.now()
    cache.set(HEARTBEAT_KEY, now.isoformat(), None)
    return now.isoformat()


def worker_last_seen():
    value = cache.get(HEARTBEAT_KEY)
    return datetime.datetime.fromisoformat(value) if value else None


def check() -> dict:
    """{'database': bool, 'cache': bool, 'worker': bool, 'worker_last_seen': iso|None}."""
    status = {'database': False, 'cache': False, 'worker': False, 'worker_last_seen': None}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        status['database'] = True
    except Exception:  # noqa: BLE001 — any failure means "down"
        logger.warning('Health check: database unreachable', exc_info=True)
    try:
        cache.set('health:probe', 1, 30)
        status['cache'] = cache.get('health:probe') == 1
    except Exception:  # noqa: BLE001
        logger.warning('Health check: cache unusable', exc_info=True)
    if status['cache']:
        last_seen = worker_last_seen()
        status['worker_last_seen'] = last_seen.isoformat() if last_seen else None
        status['worker'] = bool(last_seen and timezone.now() - last_seen
                                <= datetime.timedelta(minutes=settings.WORKER_HEARTBEAT_MAX_AGE_MINUTES))
    return status


@never_cache
def healthz(request):
    status = check()
    healthy = status['database'] and status['cache'] and status['worker']
    return JsonResponse({'ok': healthy, **status}, status=200 if healthy else 503)


def failed_tasks_since(moment):
    from django_q.models import Failure

    return list(Failure.objects.filter(stopped__gt=moment).order_by('stopped'))


def alert_if_unhealthy() -> list[str]:
    """Email ADMINS about problems; returns them (for the command's output).
    A stopped worker is re-alerted at most hourly; each failed background
    job is reported once."""
    problems = []
    status = check()
    if not status['database']:
        problems.append('The database is unreachable.')
    if not status['cache']:
        problems.append('The cache (database cache table) is unusable.')
    if status['cache'] and not status['worker']:
        seen = status['worker_last_seen'] or 'never'
        if cache.add(ALERT_THROTTLE_KEY, 1, 3600):
            problems.append(
                f'The background worker (qcluster) looks stopped — last heartbeat: {seen}. Payment confirmations, '
                'reminders, backups and the privacy clean-up are not running. Restart it: python manage.py qcluster',
            )
    if status['database']:
        since_value = cache.get(LAST_FAILURE_CHECK_KEY) if status['cache'] else None
        since = datetime.datetime.fromisoformat(since_value) if since_value else timezone.now() - datetime.timedelta(hours=1)
        failures = failed_tasks_since(since)
        if status['cache']:
            cache.set(LAST_FAILURE_CHECK_KEY, timezone.now().isoformat(), None)
        for failure in failures:
            problems.append(f'Background job {failure.func} failed at {failure.stopped:%Y-%m-%d %H:%M}: {str(failure.result)[:300]}')
    if problems:
        mail_admins(f'{len(problems)} problem(s) on {settings.JOURNAL_NAME}', '\n\n'.join(problems), fail_silently=True)
    return problems
