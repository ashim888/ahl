from django.core.management.base import BaseCommand

from ajna_health_lens.health import alert_if_unhealthy


class Command(BaseCommand):
    """Run from the server's cron every 15 minutes:
        */15 * * * * cd /path/to/site && .venv/bin/python manage.py check_health
    Emails ADMINS if the worker stopped or a background job failed."""

    help = 'Check the database, cache and background worker; email ADMINS about problems.'

    def handle(self, *args, **options):
        problems = alert_if_unhealthy()
        if problems:
            for problem in problems:
                self.stdout.write(self.style.ERROR(problem))
        else:
            self.stdout.write(self.style.SUCCESS('All healthy.'))
