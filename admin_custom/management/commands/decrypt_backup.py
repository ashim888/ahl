import getpass
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ajna_health_lens.backups import BackupError, decrypt


class Command(BaseCommand):
    """Turn an emailed backup (.sql.gz.enc) back into a .sql.gz you can restore."""

    help = 'Decrypt an emailed database backup. Asks for the backup password unless BACKUP_ENCRYPTION_PASSWORD is set.'

    def add_arguments(self, parser):
        parser.add_argument('file', help='The .sql.gz.enc attachment.')

    def handle(self, *args, file, **options):
        source = Path(file)
        if not source.exists():
            raise CommandError(f'{source} not found.')
        password = settings.BACKUP_ENCRYPTION_PASSWORD or getpass.getpass('Backup password: ')
        try:
            data = decrypt(source.read_bytes(), password)
        except BackupError as exc:
            raise CommandError(str(exc))
        target = source.with_suffix('') if source.suffix == '.enc' else source.with_name(source.name + '.sql.gz')
        target.write_bytes(data)
        self.stdout.write(self.style.SUCCESS(f'Wrote {target} — restore with: gunzip {target} && mysql <database> < {target.with_suffix("")}'))
