from django.core.mail import send_mail
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone

from .models import User

EMAIL_TEMPLATES = {
    User.VerificationStatus.APPROVED: 'users/email/verification_approved.html',
    User.VerificationStatus.REJECTED: 'users/email/verification_rejected.html',
}


@receiver(pre_save, sender=User)
def stamp_and_notify_verification_status_change(sender, instance, **kwargs):
    """Stamp verification_status_changed_at and email the user whenever
    verification_status changes — covers admin actions, the VerificationQueue
    view, and any other code path that edits the field directly.
    """
    if instance._state.adding:
        return

    previous = User.objects.filter(pk=instance.pk).values_list('verification_status', flat=True).first()
    if previous is None or previous == instance.verification_status:
        return

    instance.verification_status_changed_at = timezone.now()

    template = EMAIL_TEMPLATES.get(instance.verification_status)
    if template:
        body = render_to_string(template, {'user': instance})
        send_mail(
            subject=f'Your {instance.verification_status} verification status — Ajna Health Lens',
            message=body,
            from_email=None,
            recipient_list=[instance.email],
        )
