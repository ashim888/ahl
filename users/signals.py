from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse
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

    body = render_to_string('users/email/new_pending_verification.html', {
        'user': instance,
        'verification_queue_url': f"{settings.SITE_BASE_URL}{reverse('users:verification_queue')}",
    })
    send_mail(
        subject=f'New pending verification: {instance.email}',
        message=body,
        from_email=None,
        recipient_list=recipients,
    )
