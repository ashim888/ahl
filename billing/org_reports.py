"""Usage reports for organizations (institutional subscriptions).

What an organization gets, per its plan's promises:
- a dashboard for its managers (/organization/ — billing/org_views.py):
  seats, active readers, reads per month, top articles and sections, each
  member's read count and last visit, invoices, renewal date, account manager;
- a monthly usage email with a CSV attached (send_monthly_reports, 1st of
  the month on the qcluster worker);
- renewal reminders 30 and 7 days before the deal ends (send_renewal_reminders, daily).

Privacy: organizations see *how many* articles each member read, never
*which* — reading health stories can reveal something personal. Top
articles are shown for the organization as a whole only.
"""
import csv
import datetime
import io
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count, Max
from django.db.models.functions import TruncMonth
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Organization, OrganizationRead

logger = logging.getLogger(__name__)

RENEWAL_REMINDER_DAYS = (30, 7)


def month_bounds(day: datetime.date):
    start = day.replace(day=1)
    end = (start + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    return start, end


def previous_month(today=None):
    first_of_this = (today or timezone.localdate()).replace(day=1)
    return month_bounds(first_of_this - datetime.timedelta(days=1))


def summary(org: Organization, start: datetime.date, end: datetime.date) -> dict:
    """Usage between start and end (inclusive)."""
    reads = OrganizationRead.objects.filter(organization=org, read_on__gte=start, read_on__lte=end)
    members = list(org.active_members.select_related('user').order_by('user__first_name', 'user__last_name'))
    per_member = dict(reads.values('user').annotate(n=Count('pk')).values_list('user', 'n'))
    last_read = dict(
        OrganizationRead.objects.filter(organization=org).values('user').annotate(last=Max('read_on')).values_list('user', 'last'),
    )
    for member in members:
        member.period_reads = per_member.get(member.user_id, 0)
        member.last_read = last_read.get(member.user_id)
    top_articles = list(
        reads.exclude(article=None).values('article__title', 'article__slug').annotate(n=Count('pk')).order_by('-n')[:10],
    )
    top_sections = list(
        reads.exclude(article__section=None).values('article__section__name').annotate(n=Count('pk')).order_by('-n')[:8],
    )
    return {
        'organization': org, 'start': start, 'end': end,
        'reads': reads.count(),
        'active_readers': reads.exclude(user=None).values('user').distinct().count(),
        'members': members,
        'member_count': len(members),
        'seats': org.seats,
        'seats_left': org.seats_left,
        'top_articles': top_articles,
        'top_sections': top_sections,
    }


def monthly_series(org: Organization, months: int = 12, today=None) -> list[dict]:
    """[{'label': 'Oct 2026', 'reads': n, 'pct': bar height}] — oldest first."""
    today = today or timezone.localdate()
    starts = []
    cursor = today.replace(day=1)
    for _ in range(months):
        starts.append(cursor)
        cursor = (cursor - datetime.timedelta(days=1)).replace(day=1)
    starts.reverse()
    counts = {
        (row['month'].year, row['month'].month): row['n']
        for row in OrganizationRead.objects.filter(organization=org, read_on__gte=starts[0])
        .annotate(month=TruncMonth('read_on')).values('month').annotate(n=Count('pk'))
    }
    series = [{'label': start.strftime('%b %Y'), 'reads': counts.get((start.year, start.month), 0)} for start in starts]
    peak = max([point['reads'] for point in series] + [1])
    for point in series:
        point['pct'] = round(point['reads'] / peak * 100)
    return series


def csv_report(org: Organization, start: datetime.date, end: datetime.date) -> str:
    data = summary(org, start, end)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([f'{settings.JOURNAL_NAME} — usage report for {org.name}', f'{start:%d %b %Y} – {end:%d %b %Y}'])
    writer.writerow([])
    writer.writerow(['Articles read', data['reads']])
    writer.writerow(['Members who read', data['active_readers']])
    writer.writerow(['Members', data['member_count']])
    writer.writerow(['Seats', data['seats'] or 'Unlimited'])
    writer.writerow([])
    writer.writerow(['Member', 'Email', 'Joined', 'Articles read in period', 'Last read'])
    for member in data['members']:
        writer.writerow([
            member.user.get_full_name(), member.user.email, f'{member.joined_at:%Y-%m-%d}',
            member.period_reads, f'{member.last_read:%Y-%m-%d}' if member.last_read else '',
        ])
    writer.writerow([])
    writer.writerow(['Most-read articles (whole organization)', 'Reads'])
    for row in data['top_articles']:
        writer.writerow([row['article__title'], row['n']])
    return out.getvalue()


def _recipients(org: Organization) -> list[str]:
    emails = {org.contact_email} if org.contact_email else set()
    emails |= set(org.active_members.filter(is_manager=True).values_list('user__email', flat=True))
    return sorted(email for email in emails if email)


def send_report(org: Organization, start=None, end=None) -> bool:
    """Email the usage report for [start, end] (default: last month)."""
    if start is None:
        start, end = previous_month()
    recipients = _recipients(org)
    if not recipients:
        return False
    context = {
        **summary(org, start, end), 'journal_name': settings.JOURNAL_NAME,
        'dashboard_url': f"{settings.SITE_BASE_URL}{reverse('billing:org_dashboard')}",
        'account_manager': org.account_manager,
    }
    message = EmailMultiAlternatives(
        subject=f'{org.name}: your {settings.JOURNAL_NAME} usage for {start:%B %Y}',
        body=render_to_string('billing/email/org_usage_report.txt', context),
        to=recipients,
        cc=[org.account_manager.email] if org.account_manager else [],
    )
    message.attach_alternative(render_to_string('billing/email/org_usage_report.html', context), 'text/html')
    message.attach(f'{org.name}-usage-{start:%Y-%m}.csv'.replace(' ', '-'), csv_report(org, start, end), 'text/csv')
    try:
        message.send()
    except Exception:  # noqa: BLE001 — one failed send mustn't stop the others
        logger.exception('Usage report for %s failed', org)
        return False
    return True


def send_monthly_reports() -> int:
    """1st of each month: last month's report to every organization whose
    deal covered any of it."""
    start, end = previous_month()
    sent = 0
    for org in Organization.objects.filter(start_date__lte=end, end_date__gte=start):
        if send_report(org, start, end):
            sent += 1
    return sent


def send_renewal_reminders() -> int:
    """Daily: 30 and 7 days before a deal ends, and once after it ended —
    to the organization's contact and managers, copying the account manager
    (or the editors, when there's none)."""
    from ajna_health_lens.mail import send_templated_email
    from users.models import User

    today = timezone.localdate()
    sent = 0
    for org in Organization.objects.filter(is_active=True, end_date__gte=today - datetime.timedelta(days=3),
                                           end_date__lte=today + datetime.timedelta(days=max(RENEWAL_REMINDER_DAYS))):
        days_left = (org.end_date - today).days
        if days_left < 0:
            stage = 'ended'
        else:
            due = sorted(n for n in RENEWAL_REMINDER_DAYS if days_left <= n)
            stage = str(due[0]) if due else None
        marker = f'{org.end_date}:{stage}'
        if stage is None or marker in (org.reminders_sent or []):
            continue
        staff = [org.account_manager.email] if org.account_manager else list(
            User.objects.filter(role__in=User.SENIOR_STAFF_ROLES, is_active=True).values_list('email', flat=True),
        )
        recipients = _recipients(org) + staff
        if recipients and send_templated_email(
            subject=(f'{org.name}: your {settings.JOURNAL_NAME} subscription has ended' if stage == 'ended'
                     else f'{org.name}: your {settings.JOURNAL_NAME} subscription ends in {days_left} days'),
            template='billing/email/org_renewal_reminder',
            context={'org': org, 'stage': stage, 'days_left': days_left, 'contact_email': settings.JOURNAL_CONTACT_EMAIL,
                     'account_manager': org.account_manager},
            recipient_list=sorted(set(recipients)),
        ):
            sent += 1
        # Mark the earlier (larger) stages too, so a missed day never sends a stale reminder.
        if stage == 'ended':
            done = [str(n) for n in RENEWAL_REMINDER_DAYS] + ['ended']
        else:
            done = [str(n) for n in RENEWAL_REMINDER_DAYS if n >= int(stage)]
        org.reminders_sent = sorted(set(org.reminders_sent or []) | {f'{org.end_date}:{s}' for s in done})
        org.save(update_fields=['reminders_sent'])
    return sent
