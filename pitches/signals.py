from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse

from articles.models import Article
from users.models import User

from .models import StoryPitch

# Same pattern as users/signals.py — SUBMITTED has no template (that's the
# state a pitch is created in, not transitioned into) and PUBLISHED is set
# by the Article-side signal below, not an editor decision, so no email for
# it either — the ACCEPTED email already told the submitter what's happening.
EMAIL_TEMPLATES = {
    StoryPitch.Status.IN_REVIEW: 'pitches/email/pitch_in_review.html',
    StoryPitch.Status.ACCEPTED: 'pitches/email/pitch_accepted.html',
    StoryPitch.Status.REJECTED: 'pitches/email/pitch_rejected.html',
}


@receiver(pre_save, sender=StoryPitch)
def notify_on_status_change(sender, instance, **kwargs):
    if instance._state.adding:
        return

    previous = StoryPitch.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
    if previous is None or previous == instance.status:
        return

    template = EMAIL_TEMPLATES.get(instance.status)
    # contact_email covers both an account's email and an anonymous
    # submitter's typed-in one (see StoryPitch.contact_email) — guarded
    # since an anonymous pitch's email is user input, not guaranteed
    # present at the DB level the way an account's email is.
    if template and instance.contact_email:
        body = render_to_string(template, {'pitch': instance})
        send_mail(
            subject=f'Update on your story pitch: "{instance.title}"',
            message=body,
            from_email=None,
            recipient_list=[instance.contact_email],
        )


@receiver(post_save, sender=StoryPitch)
def notify_editorial_staff_of_new_pitch(sender, instance, created, **kwargs):
    """Previously the only way an EiC/Admin learned about a new pitch was
    by visiting the queue or the Dashboard home KPI row — invisible if they
    landed anywhere else first. Pitches are open-submission with no login
    required, so this is the only heads-up a busy queue gets.
    """
    if not created:
        return

    recipients = list(
        User.objects.filter(role__in=User.SENIOR_STAFF_ROLES, is_active=True).values_list('email', flat=True),
    )
    if not recipients:
        return

    body = render_to_string('pitches/email/new_pitch_submitted.html', {
        'pitch': instance,
        'pitch_queue_url': f"{settings.SITE_BASE_URL}{reverse('pitches:manage_pitch_queue')}",
    })
    send_mail(
        subject=f'New story pitch: "{instance.title}"',
        message=body,
        from_email=None,
        recipient_list=recipients,
    )


@receiver(pre_save, sender=Article)
def sync_pitch_status_on_article_publish(sender, instance, **kwargs):
    """When an Article promoted from a pitch gets published, reflect that
    on the pitch too — the only pitch status transition that isn't an
    editor decision, so it lives here rather than in pitches/views.py.
    """
    if instance._state.adding or not instance.pk:
        return
    if instance.status != Article.Status.PUBLISHED:
        return
    pitch = StoryPitch.objects.filter(article_id=instance.pk).exclude(status=StoryPitch.Status.PUBLISHED).first()
    if pitch:
        pitch.status = StoryPitch.Status.PUBLISHED
        pitch.save(update_fields=['status'])
