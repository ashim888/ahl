"""Best-effort notification email — a transient SMTP failure here should
never block the model save or request that triggered it. Every current
call site is exactly that shape: a pre_save/post_save signal notifying
someone about a status change that already happened (or is about to), or a
public signup endpoint whose actual side effect (creating a Subscriber row)
already succeeded by the time the confirmation email is sent. None of them
should turn into a 500, or — worse, for a pre_save signal — abort the save
itself, just because the mail server is briefly unreachable.

Not used by newsletter/tasks.py's bulk send: that already runs on an async
worker (a failure there doesn't block a live request), and needs its own,
more granular per-recipient handling — see send_newsletter_issue.
"""
import logging

from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_notification_email(*, subject, message, recipient_list, from_email=None, html_message=None):
    """Same signature as django.core.mail.send_mail, minus fail_silently
    (this always "fails silently" to the caller — that's the point — but
    logs loudly, unlike Django's own fail_silently=True which discards the
    error entirely). Returns True/False in case a future caller wants to
    react to a failure; none currently do.
    """
    try:
        send_mail(
            subject=subject, message=message, from_email=from_email,
            recipient_list=recipient_list, html_message=html_message,
        )
        return True
    except Exception:
        # Deliberately broad — every failure mode here (SMTPException,
        # socket/DNS errors, an auth failure) should be treated the same
        # way: log it, don't propagate. This is a boundary with an external
        # system, not application logic, so a blanket catch is the correct
        # choice here rather than the code smell it usually is.
        logger.exception('Failed to send notification email (subject=%r, recipients=%r)', subject, recipient_list)
        return False
