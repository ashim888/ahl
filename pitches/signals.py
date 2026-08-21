from django.core.mail import send_mail
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.template.loader import render_to_string

from articles.models import Article

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
    if template:
        body = render_to_string(template, {'pitch': instance})
        send_mail(
            subject=f'Update on your story pitch: "{instance.title}"',
            message=body,
            from_email=None,
            recipient_list=[instance.submitter.email],
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
