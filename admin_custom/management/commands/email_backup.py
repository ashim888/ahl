from django.core.management.base import BaseCommand

from ajna_health_lens.backups import email_backup


class Command(BaseCommand):
    """Run the nightly encrypted database backup email now (ajna_health_lens/backups.py)."""

    help = 'Dump, encrypt and email the database to BACKUP_EMAIL.'

    def handle(self, *args, **options):
        self.stdout.write(email_backup())
