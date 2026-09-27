from django.core.management.base import BaseCommand

from admin_custom.retention import prune_analytics_events, retention_days


class Command(BaseCommand):
    """Manual run of the daily analytics clean-up (admin_custom/retention.py)."""

    help = 'Delete page-view, keyword and ad events older than ANALYTICS_RETENTION_DAYS (default 400).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=None, help='Override the retention period for this run.')

    def handle(self, *args, **options):
        days = options['days'] or retention_days()
        deleted = prune_analytics_events(days)
        for name, count in deleted.items():
            self.stdout.write(f'{name}: {count} deleted')
        self.stdout.write(self.style.SUCCESS(f'Kept the last {days} days.'))
