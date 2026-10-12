"""Email a notice to readers — for a data-breach notification
(INCIDENT_RESPONSE.md) or another important account notice.

    python manage.py notify_users --subject "..." --message-file notice.txt --emails affected.txt
    python manage.py notify_users --subject "..." --message-file notice.txt --all-active --send

Dry run by default: prints who would be emailed. Add --send to send.
`{first_name}` in the message is replaced per person. Deleted (erased)
accounts are never emailed.
"""
from django.core.management.base import BaseCommand, CommandError

from ajna_health_lens.mail import send_notification_email
from users.models import User


class Command(BaseCommand):
    help = 'Email a notice (e.g. a data-breach notification) to listed or all active accounts. Dry run unless --send.'

    def add_arguments(self, parser):
        parser.add_argument('--subject', required=True)
        parser.add_argument('--message-file', required=True, help='Plain-text body; {first_name} is filled in.')
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--emails', help='File with one email address per line.')
        group.add_argument('--all-active', action='store_true', help='Every active account.')
        parser.add_argument('--send', action='store_true', help='Actually send (default: only list recipients).')

    def handle(self, *args, subject, message_file, emails=None, all_active=False, send=False, **options):
        try:
            with open(message_file, encoding='utf-8') as handle:
                body = handle.read()
        except OSError as exc:
            raise CommandError(f'Could not read {message_file}: {exc}')
        users = list(User.objects.filter(is_active=True, erased_at__isnull=True).order_by('email'))
        if emails:
            with open(emails, encoding='utf-8') as handle:
                wanted = {line.strip().lower() for line in handle if line.strip()}
            users = [user for user in users if user.email.lower() in wanted]
            for missing in sorted(wanted - {user.email.lower() for user in users}):
                self.stdout.write(self.style.WARNING(f'No active account for {missing}'))
        self.stdout.write(f'{len(users)} recipient(s).')
        if not send:
            for user in users[:50]:
                self.stdout.write(f'  {user.email}')
            self.stdout.write('Dry run — nothing sent. Add --send to send.')
            return
        sent = 0
        for user in users:
            if send_notification_email(
                subject=subject, message=body.replace('{first_name}', user.first_name or 'there'), recipient_list=[user.email],
            ):
                sent += 1
        self.stdout.write(self.style.SUCCESS(f'Sent {sent} of {len(users)}.'))
