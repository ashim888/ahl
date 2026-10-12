"""The organization dashboard (/organization/) — for an institution's own
managers (OrganizationMember.is_manager): usage, members, invitations,
invoices and renewal. Staff manage the same organizations from
/manage/billing/organizations/ (billing/views.py)."""
import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from ajna_health_lens.mail import send_templated_email

from . import org_reports
from .models import Organization, OrganizationMember, Payment

INVITES_PER_REQUEST = 20


def managed_organizations(user):
    if not user.is_authenticated:
        return Organization.objects.none()
    return Organization.objects.filter(
        members__user=user, members__is_manager=True, members__removed_at__isnull=True,
    ).distinct()


def _organization(request, pk=None):
    orgs = managed_organizations(request.user)
    org = orgs.filter(pk=pk).first() if pk else orgs.order_by('-end_date').first()
    if org is None:
        raise Http404
    return org


def _period(request):
    """(start, end) of ?month=YYYY-MM (default: this month)."""
    try:
        start = datetime.datetime.strptime(request.GET.get('month', ''), '%Y-%m').date()
    except ValueError:
        start = timezone.localdate().replace(day=1)
    start, end = org_reports.month_bounds(start)
    return start, end


@login_required
def dashboard(request, pk=None):
    org = _organization(request, pk)
    start, end = _period(request)
    removed = org.members.filter(removed_at__isnull=False).select_related('user').order_by('-removed_at')
    return render(request, 'billing/org_dashboard.html', {
        **org_reports.summary(org, start, end),
        'series': org_reports.monthly_series(org),
        'removed_members': removed,
        'payments': Payment.objects.filter(organization=org, status__in=[Payment.Status.SUCCESS, Payment.Status.REFUNDED]),
        'other_orgs': managed_organizations(request.user).exclude(pk=org.pk),
        'months': [org_reports.month_bounds(timezone.localdate().replace(day=1) - datetime.timedelta(days=31 * i))[0]
                   for i in range(12)],
        'days_left': (org.end_date - timezone.localdate()).days,
        'contact_email': settings.JOURNAL_CONTACT_EMAIL,
    })


@login_required
def report_csv(request, pk):
    org = _organization(request, pk)
    start, end = _period(request)
    response = HttpResponse(org_reports.csv_report(org, start, end), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="usage-{start:%Y-%m}.csv"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_POST
def member_remove(request, pk, member_pk):
    """Take someone off the subscription (left the organization): access
    ends, the seat is freed, and they can't rejoin by themselves."""
    org = _organization(request, pk)
    member = get_object_or_404(OrganizationMember, pk=member_pk, organization=org, removed_at__isnull=True)
    member.removed_at = timezone.now()
    member.is_manager = False
    member.save(update_fields=['removed_at', 'is_manager'])
    send_templated_email(
        subject=_('You no longer read %(journal)s through %(org)s') % {'journal': settings.JOURNAL_NAME, 'org': org.name},
        template='billing/email/org_member_removed',
        context={'org': org, 'user': member.user, 'plans_url': f"{settings.SITE_BASE_URL}{reverse('billing:plan_browse')}"},
        recipient_list=[member.user.email],
    )
    messages.success(request, _('%(name)s was removed — their seat is free again.') % {'name': member.user.get_full_name()})
    return redirect('billing:org_dashboard_for', pk=org.pk)


@login_required
@require_POST
def member_restore(request, pk, member_pk):
    org = _organization(request, pk)
    member = get_object_or_404(OrganizationMember, pk=member_pk, organization=org, removed_at__isnull=False)
    if org.seats is not None and org.active_members.count() >= org.seats:
        messages.error(request, _('No seats left — remove someone else first, or ask us for more seats.'))
    else:
        member.removed_at = None
        member.save(update_fields=['removed_at'])
        messages.success(request, _('%(name)s can read with your subscription again.') % {'name': member.user.get_full_name()})
    return redirect('billing:org_dashboard_for', pk=org.pk)


@login_required
@require_POST
def member_manager(request, pk, member_pk):
    """Make a member a dashboard manager, or stop them being one."""
    org = _organization(request, pk)
    member = get_object_or_404(OrganizationMember, pk=member_pk, organization=org, removed_at__isnull=True)
    if member.user_id == request.user.pk:
        messages.error(request, _('You can’t change your own manager access.'))
    else:
        member.is_manager = not member.is_manager
        member.save(update_fields=['is_manager'])
    return redirect('billing:org_dashboard_for', pk=org.pk)


@login_required
@require_POST
@ratelimit(key='user', rate='60/d', method='POST', block=False)
def invite(request, pk):
    """Email colleagues how to join: sign up (or in) with their work address
    and confirm it. Only addresses at the organization's domains."""
    org = _organization(request, pk)
    if getattr(request, 'limited', False):
        messages.error(request, _('That’s a lot of invitations for one day — please try again tomorrow, or ask us.'))
        return redirect('billing:org_dashboard_for', pk=org.pk)
    raw = request.POST.get('emails', '').replace(',', '\n').replace(';', '\n')
    addresses = [line.strip().lower() for line in raw.splitlines() if line.strip()][:INVITES_PER_REQUEST]
    sent, skipped = [], []
    for address in addresses:
        try:
            validate_email(address)
        except ValidationError:
            skipped.append(address)
            continue
        if not org.matches_email(address):
            skipped.append(address)
            continue
        if send_templated_email(
            subject=_('%(org)s gives you free access to %(journal)s') % {'org': org.name, 'journal': settings.JOURNAL_NAME},
            template='billing/email/org_invite',
            context={'org': org, 'email': address, 'inviter': request.user,
                     'register_url': f"{settings.SITE_BASE_URL}{reverse('users:register')}",
                     'login_url': f"{settings.SITE_BASE_URL}{reverse('users:login')}"},
            recipient_list=[address],
        ):
            sent.append(address)
    if sent:
        messages.success(request, _('Invitation sent to %(n)s colleague(s).') % {'n': len(sent)})
    if skipped:
        messages.warning(request, _('Not sent (not an address at %(domains)s): %(list)s') % {
            'domains': ', '.join(org.domains), 'list': ', '.join(skipped)})
    return redirect('billing:org_dashboard_for', pk=org.pk)
