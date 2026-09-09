"""Runs on a django_q worker (`python manage.py qcluster`), triggered either
by newsletter/views.py's compose view via django_q.tasks.async_task (kept
out of the request/response cycle since a real subscriber list makes this a
send-many-emails loop that would otherwise block a submit), or by the
weekly-digest django_q Schedule (see send_weekly_digest_issue below and
0003_weekly_digest_schedule.py) — same worker, same send path either way.
"""
import datetime
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from articles.models import Article

from .emails import issue_email_text_body, render_issue_email
from .models import NewsletterIssue
from .recipients import confirmed_recipients

logger = logging.getLogger(__name__)

DIGEST_LOOKBACK_DAYS = 7
DIGEST_ARTICLE_LIMIT = 5


def send_newsletter_issue(issue_id):
    issue = NewsletterIssue.objects.get(pk=issue_id)
    subscribers = list(confirmed_recipients(issue.audience))

    # One SMTP connection for the whole run, not one per recipient —
    # send_mail() (the previous approach) opens and closes a fresh
    # connection on every call via its own implicit get_connection(), which
    # is fine for a handful of emails but turns into hundreds of redundant
    # TCP/TLS handshakes against a real ESP at actual subscriber-list scale,
    # and risks hitting a provider's per-connection rate limit well before
    # its per-account send limit. Letting connection.open() itself raise
    # uncaught is deliberate — if the connection can't even be established,
    # there's nothing to isolate per-recipient; the task should just fail.
    connection = get_connection()
    connection.open()

    sent = 0
    failed = 0
    try:
        for subscriber in subscribers:
            unsubscribe_url = f"{settings.SITE_BASE_URL}{reverse('newsletter:unsubscribe', args=[subscriber.unsubscribe_token])}"
            # render_issue_email is the same branded template the editor
            # saw in the compose-page preview (newsletter/emails.py) — a
            # subscriber's inbox and that preview can't drift apart.
            html_body = render_issue_email(issue.subject, issue.body_html, unsubscribe_url)
            text_body = issue_email_text_body(issue.subject, issue.body_html, unsubscribe_url)
            message = EmailMultiAlternatives(
                subject=issue.subject, body=text_body, to=[subscriber.email], connection=connection,
            )
            message.attach_alternative(html_body, 'text/html')
            try:
                message.send()
                sent += 1
            except Exception:
                # One bad recipient (a rejected mailbox, a provider hiccup
                # on that one message) shouldn't sink the rest of the
                # batch — log it and keep going. Contrast with a total
                # failure below, which does need to surface.
                failed += 1
                logger.exception('Failed to send newsletter issue %s to %s', issue_id, subscriber.email)
    finally:
        connection.close()

    if failed and sent == 0:
        # Every attempted send failed (bad credentials, provider outage,
        # ...) — leaving sent_at unset (not "set it, then raise anyway") is
        # what makes this show correctly: NewsletterIssue.get_send_status()
        # checks sent_at *before* the task's own success flag, so setting
        # it here regardless would report a plain "Sent" with the total
        # failure completely invisible in the editorial list. Raising lets
        # django_q mark the Task itself as failed instead, which get_send_
        # status() already knows how to surface. Known gap this doesn't
        # cover: a retry re-sends to every confirmed subscriber again,
        # including any who *did* get a copy in a partial-failure run,
        # since there's no per-subscriber delivery ledger yet.
        issue.recipient_count = 0
        issue.save(update_fields=['recipient_count'])
        raise RuntimeError(f'All {failed} send attempt(s) failed for newsletter issue {issue_id}.')

    issue.sent_at = timezone.now()
    issue.recipient_count = sent
    issue.save(update_fields=['sent_at', 'recipient_count'])
    return sent


def _weekly_digest_body(articles):
    rows = []
    for article in articles:
        url = f"{settings.SITE_BASE_URL}{reverse('articles:article_detail', args=[article.slug])}"
        rows.append(
            f'<p><a href="{url}"><strong>{escape(article.title)}</strong></a><br>{escape(article.abstract)}</p>',
        )
    return '\n'.join(rows)


def send_weekly_digest_issue():
    """Auto-composes and sends a real NewsletterIssue from the last
    DIGEST_LOOKBACK_DAYS days' published articles (ROADMAP.md Phase 10
    Session 8) — capped at DIGEST_ARTICLE_LIMIT, most recent first, by
    publication_date (when it actually went live, matching
    sections/digest.py's own recency convention). Skips entirely — no
    issue created, nothing sent — if nothing was published that week,
    rather than sending a thin or empty issue; mirrors send_topic_digests'
    "skip a reader with nothing new" rule, just at the whole-issue level
    instead of per-subscriber.

    Deliberately reuses send_newsletter_issue() for the actual send rather
    than a second, parallel send path — same branded template, same
    unsubscribe link, same per-recipient failure isolation as a
    manually-composed issue. created_by stays null (the field is already
    nullable) — a system-generated issue has no editor attached, and shows
    up in the normal /manage/newsletter/ list exactly like any other.
    """
    cutoff_date = timezone.localdate() - datetime.timedelta(days=DIGEST_LOOKBACK_DAYS)
    articles = list(
        Article.objects.filter(
            status=Article.Status.PUBLISHED, publication_date__gte=cutoff_date,
        ).order_by('-publication_date', '-created_at')[:DIGEST_ARTICLE_LIMIT],
    )
    if not articles:
        return None
    issue = NewsletterIssue.objects.create(
        subject=f'This Week at {settings.JOURNAL_NAME}',
        body_html=_weekly_digest_body(articles),
        audience=NewsletterIssue.Audience.ALL,
    )
    send_newsletter_issue(issue.pk)
    # send_newsletter_issue fetches its own copy of the row and mutates
    # that (sent_at/recipient_count) — this local `issue` object predates
    # that write, so it has to be refreshed before the caller sees it.
    issue.refresh_from_db()
    return issue
