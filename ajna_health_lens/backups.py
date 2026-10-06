"""Off-site copy of the database, by email.

Every night (qcluster schedule — admin_custom/migrations/0003_email_backup_schedule)
the database is dumped,
gzipped, ENCRYPTED with BACKUP_ENCRYPTION_PASSWORD and emailed to
BACKUP_EMAIL. Email isn't private, so the attachment is useless without the
password — keep that password somewhere other than this server (a password
manager), or the backups can't be restored.

    python manage.py email_backup            # run it now
    python manage.py decrypt_backup FILE     # -> FILE without .enc, a .sql.gz to restore

Encrypted file layout: b'AHLBK1' + 16-byte salt + Fernet token; the key is
scrypt(password, salt). Media uploads are not included (too big for email) —
backup.sh archives those on the server.
"""
import base64
import gzip
import logging
import os
import subprocess

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from django.conf import settings
from django.core.mail import EmailMessage, mail_admins
from django.utils import timezone

logger = logging.getLogger(__name__)

MAGIC = b'AHLBK1'


class BackupError(Exception):
    pass


def _key(password: str, salt: bytes) -> bytes:
    raw = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode('utf-8'))
    return base64.urlsafe_b64encode(raw)


def encrypt(data: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    return MAGIC + salt + Fernet(_key(password, salt)).encrypt(data)


def decrypt(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise BackupError('Not an encrypted backup from this site.')
    salt, token = blob[len(MAGIC):len(MAGIC) + 16], blob[len(MAGIC) + 16:]
    try:
        return Fernet(_key(password, salt)).decrypt(token)
    except InvalidToken as exc:
        raise BackupError('Wrong password, or the file is damaged.') from exc


def dump_database() -> bytes:
    """mysqldump of the default database, gzipped."""
    db = settings.DATABASES['default']
    command = [
        'mysqldump', f'--host={db.get("HOST") or "localhost"}', f'--port={db.get("PORT") or 3306}',
        f'--user={db["USER"]}', '--single-transaction', '--routines', '--triggers', '--no-tablespaces', db['NAME'],
    ]
    # MYSQL_PWD, not --password=, so the password never shows in `ps`.
    env = {**os.environ, 'MYSQL_PWD': db.get('PASSWORD') or ''}
    try:
        result = subprocess.run(command, capture_output=True, env=env, timeout=1800, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupError(f'mysqldump could not run: {exc}') from exc
    if result.returncode != 0:
        raise BackupError(f'mysqldump failed: {result.stderr.decode(errors="replace")[:500]}')
    return gzip.compress(result.stdout)


def email_backup() -> str:
    """Dump, encrypt and email the database. Returns a one-line summary.
    Any failure is emailed to ADMINS — a backup that silently stops is the
    worst kind."""
    recipient, password = settings.BACKUP_EMAIL, settings.BACKUP_ENCRYPTION_PASSWORD
    if not recipient or not password:
        message = 'Emailed backups are off: set BACKUP_EMAIL and BACKUP_ENCRYPTION_PASSWORD.'
        logger.warning(message)
        return message
    try:
        encrypted = encrypt(dump_database(), password)
        size_mb = len(encrypted) / 1_048_576
        if size_mb > settings.BACKUP_EMAIL_MAX_MB:
            raise BackupError(
                f'The encrypted backup is {size_mb:.1f} MB, over the {settings.BACKUP_EMAIL_MAX_MB} MB email limit. '
                'Move to another off-site destination (see INCIDENT_RESPONSE.md / README).',
            )
        stamp = timezone.localtime().strftime('%Y-%m-%d_%H%M')
        filename = f'{settings.DATABASES["default"]["NAME"]}-{stamp}.sql.gz.enc'
        message = EmailMessage(
            subject=f'[{settings.JOURNAL_NAME}] Database backup {stamp} ({size_mb:.1f} MB)',
            body=(
                f'The encrypted database backup for {settings.JOURNAL_NAME} is attached ({filename}).\n\n'
                'To restore it on a server with the code:\n'
                f'  python manage.py decrypt_backup {filename}\n'
                f'  gunzip {filename[:-4]} && mysql <database> < {filename[:-7]}\n\n'
                'You need the backup password (BACKUP_ENCRYPTION_PASSWORD). Keep these emails in a folder; '
                'the server only sends, it does not keep copies.'
            ),
            to=[recipient],
        )
        message.attach(filename, encrypted, 'application/octet-stream')
        message.send()
    except Exception as exc:  # noqa: BLE001 — every failure must reach a human
        # Warning, not error: an ERROR log is itself emailed to ADMINS, and the
        # explicit email below says it more clearly — one alert, not two.
        logger.warning('Emailed backup failed', exc_info=True)
        mail_admins('Database backup FAILED', f'The nightly emailed backup failed:\n\n{exc}', fail_silently=True)
        raise
    summary = f'Backup emailed to {recipient}: {filename} ({size_mb:.1f} MB).'
    logger.info(summary)
    return summary
