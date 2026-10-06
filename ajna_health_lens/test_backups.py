"""Nightly encrypted database backup by email (ajna_health_lens/backups.py)."""
import gzip
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from . import backups

SETTINGS = dict(BACKUP_EMAIL='vault@example.com', BACKUP_ENCRYPTION_PASSWORD='correct horse battery staple',
                ADMINS=[('Ops', 'ops@example.com')])


class EncryptionTests(TestCase):
    def test_round_trip_and_wrong_password(self):
        blob = backups.encrypt(b'CREATE TABLE x;', 'secret')
        self.assertTrue(blob.startswith(backups.MAGIC))
        self.assertNotIn(b'CREATE TABLE', blob)
        self.assertEqual(backups.decrypt(blob, 'secret'), b'CREATE TABLE x;')
        with self.assertRaisesMessage(backups.BackupError, 'Wrong password'):
            backups.decrypt(blob, 'guess')
        with self.assertRaisesMessage(backups.BackupError, 'Not an encrypted backup'):
            backups.decrypt(b'plain', 'secret')


@override_settings(**SETTINGS)
class EmailBackupTests(TestCase):
    def test_backup_is_emailed_encrypted_and_restorable(self):
        dump = gzip.compress(b'-- MySQL dump\nCREATE TABLE users;')
        with patch('ajna_health_lens.backups.dump_database', return_value=dump):
            summary = backups.email_backup()
        self.assertIn('vault@example.com', summary)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['vault@example.com'])
        filename, content, _ = message.attachments[0]
        self.assertTrue(filename.endswith('.sql.gz.enc'))
        self.assertNotIn(b'CREATE TABLE', content)
        # The decrypt command turns the attachment back into the dump.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / filename
            path.write_bytes(content)
            call_command('decrypt_backup', str(path), stdout=StringIO())
            self.assertEqual(gzip.decompress(path.with_suffix('').read_bytes()), b'-- MySQL dump\nCREATE TABLE users;')

    def test_off_until_configured(self):
        with self.settings(BACKUP_EMAIL=''):
            self.assertIn('off', backups.email_backup())
        self.assertEqual(mail.outbox, [])

    def test_failures_alert_the_admins(self):
        with patch('ajna_health_lens.backups.dump_database', side_effect=backups.BackupError('mysqldump failed: denied')):
            with self.assertRaises(backups.BackupError):
                backups.email_backup()
        self.assertEqual([m.to for m in mail.outbox], [['ops@example.com']])
        self.assertIn('mysqldump failed: denied', mail.outbox[0].body)

    def test_too_big_for_email_alerts_instead_of_bouncing(self):
        with self.settings(BACKUP_EMAIL_MAX_MB=0), patch('ajna_health_lens.backups.dump_database', return_value=b'x' * 2048):
            with self.assertRaises(backups.BackupError):
                backups.email_backup()
        self.assertEqual([m.to for m in mail.outbox], [['ops@example.com']])
        self.assertIn('email limit', mail.outbox[0].body)

    @unittest.skipUnless(shutil.which('mysqldump'), 'mysqldump not installed')
    def test_real_dump_of_this_database(self):
        dump = gzip.decompress(backups.dump_database())
        self.assertIn(b'CREATE TABLE `users_user`', dump)

    def test_scheduled_nightly(self):
        from django_q.models import Schedule

        self.assertEqual(Schedule.objects.get(name='email_backup_daily').func, 'ajna_health_lens.backups.email_backup')

    def test_deploy_check_warns_when_off(self):
        from articles.checks import check_backups

        with self.settings(DEBUG=False, BACKUP_EMAIL=''):
            self.assertEqual([w.id for w in check_backups(None)], ['ajna.W002'])
        with self.settings(DEBUG=False):
            self.assertEqual(check_backups(None), [])
