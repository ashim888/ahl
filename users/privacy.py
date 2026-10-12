"""Readers' privacy rights, in one place:

- export_user_data — "give me a copy of my data" (download from /account/privacy/);
- erase_user — "delete my account" (self-service, or staff acting on an
  emailed request): personal data is removed or anonymised, but the row is
  kept so tax records (receipts) and the published record (bylines,
  accepted pitches) stay intact — those are kept under a legal obligation /
  journalism, and say only "Deleted user" from then on;
- one-click unsubscribe links for the emails that aren't the newsletter
  (topic digest, renewal reminders), usable without signing in;
- privacy_housekeeping — the daily job that enforces the retention periods
  the Privacy policy promises.
"""
import datetime
import logging

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

# Retention promised in the Privacy policy (pages/migrations/0004).
COMMENT_IP_RETENTION_DAYS = 90
LOGIN_LOG_RETENTION_DAYS = 90
UNCONFIRMED_SIGNUP_RETENTION_DAYS = 30

ERASED_NAME = 'Deleted user'


def _iso(value):
    return value.isoformat() if value else None


def export_user_data(user) -> dict:
    """Everything we hold about `user` that's linked to their account, as
    plain JSON-able data (Right of access / portability)."""
    from django_comments_xtd.models import XtdComment

    from articles.models import Author, Bookmark, KeywordFollow
    from billing.models import (
        ArticleGift, ArticlePurchase, OrganizationMember, OrganizationRead, Payment, PromoRedemption, UserSubscription,
    )
    from newsletter.models import Subscriber
    from pitches.models import StoryPitch
    from sections.models import SectionFollow
    from training.models import Enrollment

    author = Author.objects.filter(user=user).first()
    return {
        'exported_at': timezone.now().isoformat(),
        'site': settings.JOURNAL_NAME,
        'account': {
            'email': user.email, 'first_name': user.first_name, 'last_name': user.last_name,
            'joined': _iso(user.date_joined), 'last_login': _iso(user.last_login), 'role': user.get_role_display(),
            'email_confirmed_at': _iso(user.email_confirmed_at), 'terms_accepted_at': _iso(user.terms_accepted_at),
            'verification_status': user.get_verification_status_display(),
            'profile': {
                field: getattr(user, field) or '' for field in (
                    'affiliation', 'department', 'orcid', 'bio', 'research_interests', 'linkedin_url',
                    'researchgate_url', 'publications',
                )
            },
            'files': {'photo': bool(user.photo), 'cv': bool(user.cv_file)},
            'email_preferences': {
                'weekly_topic_digest': user.email_topic_digest, 'renewal_reminders': user.email_renewal_reminders,
            },
        },
        'author_profile': {
            'name': author.name, 'affiliation': author.affiliation, 'bio': author.bio, 'orcid': author.orcid,
        } if author else None,
        'newsletter': [
            {'email': s.email, 'status': s.get_status_display(), 'subscribed_at': _iso(s.subscribed_at)}
            for s in (Subscriber.objects.filter(user=user) | Subscriber.objects.filter(email__iexact=user.email)).distinct()
        ],
        'subscriptions': [
            {'plan': s.plan.name, 'status': s.get_status_display(), 'start': _iso(s.start_date), 'end': _iso(s.end_date)}
            for s in UserSubscription.objects.filter(user=user).select_related('plan')
        ],
        'payments': [
            {
                'receipt': p.receipt_number, 'credit_note': p.credit_note_number, 'description': p.description,
                'price': str(p.subtotal), 'vat': str(p.vat_amount), 'total': str(p.amount), 'status': p.get_status_display(),
                'paid_via': p.get_gateway_display(), 'date': _iso(p.completed_at or p.created_at),
            }
            for p in Payment.objects.filter(user=user)
        ],
        'purchased_articles': [
            {'title': p.article.title, 'purchased_at': _iso(p.purchased_at)}
            for p in ArticlePurchase.objects.filter(user=user).select_related('article')
        ],
        'training_enrollments': [
            {'course': e.course.title, 'status': e.get_status_display(), 'payment': e.get_payment_status_display(),
             'enrolled_at': _iso(e.enrolled_at)}
            for e in Enrollment.objects.filter(user=user).select_related('course')
        ],
        'promo_codes_used': [
            {'code': r.code.code, 'used_on': r.item, 'discount_before_vat': str(r.discount_amount), 'date': _iso(r.created_at)}
            for r in PromoRedemption.objects.filter(user=user).select_related('code')
        ],
        'organizations': [
            {'organization': m.organization.name, 'joined_at': _iso(m.joined_at),
             'removed_at': _iso(m.removed_at), 'is_manager': m.is_manager,
             'articles_read_through_it': [
                 {'article': r.article.title if r.article else None, 'read_on': _iso(r.read_on)}
                 for r in OrganizationRead.objects.filter(user=user, organization=m.organization_id).select_related('article')
             ]}
            for m in OrganizationMember.objects.filter(user=user).select_related('organization')
        ],
        'saved_articles': [
            {'title': b.article.title, 'saved_at': _iso(b.bookmarked_at)}
            for b in Bookmark.objects.filter(user=user).select_related('article')
        ],
        'followed_sections': [f.section.name for f in SectionFollow.objects.filter(user=user).select_related('section')],
        'followed_topics': [f.keyword.name for f in KeywordFollow.objects.filter(user=user).select_related('keyword')],
        'gift_links': [
            {'article': g.article.title, 'created_at': _iso(g.created_at), 'expires_at': _iso(g.expires_at)}
            for g in ArticleGift.objects.filter(gifter=user).select_related('article')
        ],
        'comments': [
            {'comment': c.comment, 'name_shown': c.user_name, 'posted_at': _iso(c.submit_date),
             'on': str(c.content_object) if c.content_object else None, 'removed': c.is_removed}
            for c in (XtdComment.objects.filter(user=user) | XtdComment.objects.filter(user_email__iexact=user.email)).distinct()
        ],
        'reports_sent': [
            {'about': r.target_summary, 'reason': r.get_reason_display(), 'sent_at': _iso(r.created_at),
             'status': r.get_status_display()}
            for r in _reports_by(user)
        ],
        'story_pitches': [
            {'title': p.title, 'summary': p.summary, 'status': p.get_status_display(), 'sent_at': _iso(p.created_at)}
            for p in StoryPitch.objects.filter(submitter=user)
        ],
    }


def _reports_by(user):
    from admin_custom.models import ContentReport

    return (ContentReport.objects.filter(reporter=user) | ContentReport.objects.filter(reporter_email__iexact=user.email)).distinct()


class ErasureRefused(Exception):
    """This account can't be erased this way (staff accounts must be demoted first)."""


@transaction.atomic
def erase_user(user, *, remove_comments: bool = False) -> None:
    """Delete `user`'s personal data. Irreversible. Keeps the row (as an
    inactive "Deleted user") so receipts, published bylines and accepted
    pitches keep their history. Sends a last confirmation email to the old
    address first (after commit)."""
    from django_comments_xtd.models import XtdComment

    from articles.models import Author, Bookmark, KeywordFollow
    from billing.models import ArticleGift, MeteredArticleRead, OrganizationMember, OrganizationRead, UserSubscription
    from newsletter.models import Subscriber
    from pitches.models import StoryPitch
    from sections.models import SectionFollow

    from .models import User

    if user.erased_at:
        return
    if user.is_editorial_staff or user.is_superuser:
        raise ErasureRefused('Staff accounts must be changed to a reader role before they can be deleted.')
    old_email, first_name = user.email, user.first_name

    # Things that only exist for this person: delete.
    Bookmark.objects.filter(user=user).delete()
    KeywordFollow.objects.filter(user=user).delete()
    SectionFollow.objects.filter(user=user).delete()
    ArticleGift.objects.filter(gifter=user).delete()
    MeteredArticleRead.objects.filter(user=user).delete()
    OrganizationMember.objects.filter(user=user).delete()
    # Their reads stay in the organization's usage totals, without them.
    OrganizationRead.objects.filter(user=user).update(user=None)
    Subscriber.objects.filter(user=user).delete()
    Subscriber.objects.filter(email__iexact=old_email).delete()
    StoryPitch.objects.filter(submitter=user).exclude(
        status__in=(StoryPitch.Status.ACCEPTED, StoryPitch.Status.PUBLISHED),
    ).delete()
    # Paid access ends with the account (Refunds & cancellations, section 1).
    UserSubscription.objects.filter(user=user, status=UserSubscription.Status.ACTIVE).update(
        status=UserSubscription.Status.CANCELLED,
    )

    # Published / editorial record: keep, without the person's details.
    StoryPitch.objects.filter(submitter=user).update(submitter_name=ERASED_NAME, submitter_email='')
    for author in Author.objects.filter(user=user):
        author.user = None
        if author.email and author.email.lower() == old_email.lower():
            author.email = ''
        author.save(update_fields=['user', 'email'])
    comments = XtdComment.objects.filter(user=user) | XtdComment.objects.filter(user_email__iexact=old_email)
    comment_ids = list(comments.values_list('pk', flat=True))
    XtdComment.objects.filter(pk__in=comment_ids).order_by().update(
        user=None, user_name=ERASED_NAME, user_email='', user_url='', ip_address=None, followup=False,
        **({'is_removed': True} if remove_comments else {}),
    )

    # Reports they sent: kept (the record of what was reported), without them.
    from admin_custom.models import ContentReport

    ContentReport.objects.filter(reporter=user).update(reporter=None, reporter_name='', reporter_email='')
    ContentReport.objects.filter(reporter_email__iexact=old_email).update(reporter_name='', reporter_email='')

    # Security logs keyed on the email address.
    try:
        from axes.models import AccessAttempt, AccessFailureLog, AccessLog

        for model in (AccessAttempt, AccessFailureLog, AccessLog):
            model.objects.filter(username__iexact=old_email).delete()
    except ImportError:  # pragma: no cover — axes is installed
        pass

    # The account itself.
    for file_field in (user.photo, user.cv_file):
        if file_field:
            file_field.delete(save=False)
    user.email = f'deleted-{user.pk}@deleted.invalid'
    user.first_name, user.last_name = ERASED_NAME, ''
    for field in ('affiliation', 'department', 'orcid', 'bio', 'research_interests', 'linkedin_url',
                  'researchgate_url', 'publications'):
        setattr(user, field, None)
    user.set_unusable_password()  # also signs out every other session
    user.is_active = False
    user.role = User.Role.UNVERIFIED
    user.is_verified = False
    user.verification_status = User.VerificationStatus.NOT_REQUESTED
    user.email_confirmed_at = None
    user.email_topic_digest = user.email_renewal_reminders = False
    user.erased_at = timezone.now()
    user.save()
    logger.info('Erased personal data of user %s', user.pk)

    from ajna_health_lens.mail import send_templated_email

    transaction.on_commit(lambda: send_templated_email(
        subject=f'Your {settings.JOURNAL_NAME} account has been deleted',
        template='users/email/account_deleted',
        context={'first_name': first_name, 'contact_email': settings.JOURNAL_CONTACT_EMAIL},
        recipient_list=[old_email],
    ))


# -- One-click unsubscribe for account emails ------------------------------

UNSUBSCRIBE_SALT = 'users.email-unsubscribe'
EMAIL_KINDS = {
    'digest': ('email_topic_digest', _('the weekly digest of topics you follow')),
    'reminders': ('email_renewal_reminders', _('subscription renewal reminders')),
}


def unsubscribe_url(user, kind: str) -> str:
    token = signing.dumps({'u': user.pk, 'k': kind}, salt=UNSUBSCRIBE_SALT, compress=True)
    return f"{settings.SITE_BASE_URL}{reverse('users:email_unsubscribe', args=[token])}"


def read_unsubscribe_token(token: str):
    """(user, kind) or (None, None). These links don't expire — an old
    email's unsubscribe link must keep working."""
    from .models import User

    try:
        data = signing.loads(token, salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return None, None
    user = User.objects.filter(pk=data.get('u')).first()
    kind = data.get('k')
    if user is None or kind not in EMAIL_KINDS:
        return None, None
    return user, kind


def list_unsubscribe_headers(url: str) -> dict:
    """RFC 8058 one-click unsubscribe — Gmail/Yahoo show an "Unsubscribe"
    button and POST to the URL."""
    return {'List-Unsubscribe': f'<{url}>', 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'}


# -- Daily retention clean-up ------------------------------------------------

def privacy_housekeeping() -> dict:
    """Enforces the retention periods in the Privacy policy. Runs daily on
    the qcluster worker (users/migrations/0010_privacy_housekeeping_schedule)."""
    from django.contrib.sessions.models import Session
    from django_comments_xtd.models import XtdComment

    from newsletter.models import Subscriber

    now = timezone.now()
    done = {
        # .order_by(): MySQL rejects the comment model's default ORDER BY in
        # a multi-table UPDATE.
        'comment_ips_cleared': XtdComment.objects.filter(
            submit_date__lt=now - datetime.timedelta(days=COMMENT_IP_RETENTION_DAYS), ip_address__isnull=False,
        ).order_by().update(ip_address=None),
        'unconfirmed_newsletter_signups_deleted': Subscriber.objects.filter(
            status=Subscriber.Status.PENDING,
            subscribed_at__lt=now - datetime.timedelta(days=UNCONFIRMED_SIGNUP_RETENTION_DAYS),
        ).delete()[0],
        'expired_sessions_deleted': Session.objects.filter(expire_date__lt=now).delete()[0],
    }
    from axes.models import AccessAttempt, AccessFailureLog, AccessLog

    cutoff = now - datetime.timedelta(days=LOGIN_LOG_RETENTION_DAYS)
    done['login_records_deleted'] = sum(
        model.objects.filter(attempt_time__lt=cutoff).delete()[0] for model in (AccessAttempt, AccessFailureLog, AccessLog)
    )
    logger.info('Privacy housekeeping: %s', done)
    return done
