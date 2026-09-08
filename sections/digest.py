"""Weekly "what's new from what you follow" email — see ROADMAP.md Phase 10
Sessions 3 & 5 (Section- and Keyword-follows, combined into one digest, not
two). Runs on a django_q schedule (see the 0004_topic_digest_schedule
migration), the same worker process (`qcluster`) newsletter sends already
require — no new infrastructure.

Modeled on newsletter.tasks.send_newsletter_issue's one-connection,
per-recipient-isolated send loop, for the same reason: this is also a bulk
send where one bad mailbox shouldn't sink everyone after it in the list.
Not built on ajna_health_lens/mail.py:send_notification_email — that
wrapper is explicitly for a single best-effort send tied to a request/signal,
not a bulk loop (see its own docstring).
"""
import datetime
import logging

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from articles.models import Article, KeywordFollow
from users.models import User

from .models import SectionFollow

logger = logging.getLogger(__name__)

DIGEST_LOOKBACK_DAYS = 7


def _digest_body(user, articles):
    lines = [
        f'Hi {user.get_full_name()},',
        '',
        "Here's what's new this week from the topics you follow:",
        '',
    ]
    for article in articles:
        url = f"{settings.SITE_BASE_URL}{reverse('articles:article_detail', args=[article.slug])}"
        section_name = article.section.name if article.section else ''
        lines.append(f'- [{section_name}] {article.title}')
        lines.append(f'  {url}')
        lines.append('')
    lines.append(f"Manage what you follow: {settings.SITE_BASE_URL}{reverse('users:profile')}")
    lines.append('')
    lines.append(f'— {settings.JOURNAL_NAME}')
    return '\n'.join(lines)


def send_topic_digests():
    """One email per reader following at least one Section or Keyword,
    listing published articles matching either in the last
    DIGEST_LOOKBACK_DAYS days (by publication_date — when it actually went
    live, not created_at, which can predate publication by a long draft
    period), combined and de-duplicated — an article matching both a
    followed section and a followed keyword is listed once, not twice.
    Skips a reader with nothing new this week — no "nothing to report"
    filler email. Returns the number of digests actually sent, mirroring
    send_newsletter_issue's return shape.
    """
    cutoff_date = timezone.localdate() - datetime.timedelta(days=DIGEST_LOOKBACK_DAYS)
    followers = User.objects.filter(
        Q(section_follows__isnull=False) | Q(keyword_follows__isnull=False),
    ).distinct()

    connection = get_connection()
    connection.open()
    sent = 0
    try:
        for user in followers:
            section_ids = SectionFollow.objects.filter(user=user).values_list('section_id', flat=True)
            keyword_ids = KeywordFollow.objects.filter(user=user).values_list('keyword_id', flat=True)
            articles = list(
                Article.objects.filter(
                    Q(section_id__in=section_ids) | Q(keyword_tags__in=keyword_ids),
                    status=Article.Status.PUBLISHED, publication_date__gte=cutoff_date,
                ).distinct().order_by('-publication_date', '-created_at'),
            )
            if not articles:
                continue
            try:
                send_mail(
                    subject=f'Your weekly digest — {settings.JOURNAL_NAME}',
                    message=_digest_body(user, articles),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    connection=connection,
                )
                sent += 1
            except Exception:
                # Same reasoning as send_newsletter_issue's per-recipient
                # catch — one rejected mailbox shouldn't stop everyone else
                # in the list from getting their digest.
                logger.exception('Failed to send topic digest to %s', user.email)
    finally:
        connection.close()
    return sent
