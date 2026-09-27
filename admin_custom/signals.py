"""Tells senior editorial staff about new reader comments.

Comments go live without pre-moderation — a signed-in reader's immediately,
an anonymous one's once they confirm by email — so without this, abuse was
only found by someone happening to open /editorial/comments/. Same shape as
the new-pitch and new-verification alerts (pitches/signals.py,
users/signals.py): one email per event to EiC/Admin accounts.
"""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django_comments_xtd.models import XtdComment

from ajna_health_lens.mail import send_templated_email
from users.models import User


@receiver(post_save, sender=XtdComment, dispatch_uid='admin_custom.notify_staff_of_new_comment')
def notify_staff_of_new_comment(sender, instance, created, **kwargs):
    """Fires when a comment row is created — for anonymous comments that's
    the moment the emailed confirmation link is clicked (the package only
    creates the row then), so unconfirmed comments never notify anyone.
    """
    if not created or not instance.is_public:
        return
    if instance.user_id and getattr(instance.user, 'is_editorial_staff', False):
        return  # staff replying in their own threads don't need an alert

    recipients = list(
        User.objects.filter(role__in=User.SENIOR_STAFF_ROLES, is_active=True)
        .exclude(email='').values_list('email', flat=True),
    )
    if not recipients:
        return

    target = instance.content_object
    article_url = target.get_absolute_url() if hasattr(target, 'get_absolute_url') else ''
    send_templated_email(
        subject=f'New comment on "{target}"',
        template='admin_custom/email/new_comment',
        context={
            'comment': instance,
            'target': target,
            'comment_url': f'{settings.SITE_BASE_URL}{article_url}#c{instance.pk}',
            'moderation_url': f"{settings.SITE_BASE_URL}{reverse('admin_custom:manage_comment_list')}",
        },
        recipient_list=recipients,
    )
