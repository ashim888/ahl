from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from users.models import User


class Command(BaseCommand):
    """For when nobody can sign in to reset it from the dashboard (e.g. the
    only Admin lost their phone): python manage.py reset_two_step admin@example.com"""

    help = "Remove a user's two-step sign-in devices; they set it up again at their next sign-in."

    def add_arguments(self, parser):
        parser.add_argument('email')

    def handle(self, *args, email, **options):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f'No account for {email}.')
        removed = TOTPDevice.objects.filter(user=user).delete()[0] + StaticDevice.objects.filter(user=user).delete()[0]
        self.stdout.write(self.style.SUCCESS(f'Removed {removed} device(s) for {user.email}.'))
