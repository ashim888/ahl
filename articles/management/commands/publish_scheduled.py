from django.core.management.base import BaseCommand

from articles.tasks import publish_due_articles


class Command(BaseCommand):
    help = 'Publish every Scheduled article whose time has come (normally run every minute by the qcluster worker).'

    def handle(self, *args, **options):
        count = publish_due_articles()
        self.stdout.write(f'{count} scheduled article(s) published.')
