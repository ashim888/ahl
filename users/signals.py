from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from ajna_health_lens.mail import send_templated_email

from .models import User

# Template path without extension — send_templated_email renders the .txt
# and branded .html pair (see ajna_health_lens/mail.py).
EMAIL_TEMPLATES = {
    User.VerificationStatus.APPROVED: 'users/email/verification_approved',
    User.VerificationStatus.REJECTED: 'users/email/verification_rejected',
}
EMAIL_SUBJECTS = {
    User.VerificationStatus.APPROVED: f'Your {settings.JOURNAL_NAME} account is verified',
    User.VerificationStatus.REJECTED: f'Update on your {settings.JOURNAL_NAME} verification request',
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
        send_templated_email(
            subject=EMAIL_SUBJECTS[instance.verification_status],
            template=template,
            context={
                'user': instance,
                'profile_url': f"{settings.SITE_BASE_URL}{reverse('users:profile')}",
                'profile_edit_url': f"{settings.SITE_BASE_URL}{reverse('users:profile_edit')}",
            },
            recipient_list=[instance.email],
        )


@receiver(post_save, sender=User)
def notify_editorial_staff_of_new_pending_verification(sender, instance, created, **kwargs):
    """Previously the only way an EiC/Admin learned about a new pending
    registration was by visiting the queue or the Dashboard home KPI row —
    invisible if they landed anywhere else first. Matches VerificationQueueView's
    own (role-agnostic) filter: any new user defaults to verification_status
    PENDING regardless of role, so this fires for any newly created account.
    """
    if not created or instance.verification_status != User.VerificationStatus.PENDING:
        return

    recipients = list(
        User.objects.filter(role__in=User.SENIOR_STAFF_ROLES, is_active=True).values_list('email', flat=True),
    )
    if not recipients:
        return

    send_templated_email(
        subject=f'New pending verification: {instance.email}',
        template='users/email/new_pending_verification',
        context={
            'user': instance,
            'verification_queue_url': f"{settings.SITE_BASE_URL}{reverse('users:verification_queue')}",
        },
        recipient_list=recipients,
    )
