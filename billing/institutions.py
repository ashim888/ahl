"""Organization (institutional) access by email domain.

A reader gets an organization's plan when all of these hold: their email
address is confirmed (users.User.email_confirmed_at — anyone can type
someone@hospital.org at signup, only the real owner can click the link we
send there), its domain is one of the organization's, the deal is current,
and there's a seat — taken the first time they read under it
(OrganizationMember) and kept from then on.
"""
from django.db import IntegrityError, transaction

from .models import Organization, OrganizationMember

# Never accepted as an organization domain: everyone can get an address there.
PUBLIC_EMAIL_DOMAINS = {
    'gmail.com', 'googlemail.com', 'yahoo.com', 'ymail.com', 'outlook.com', 'hotmail.com', 'live.com', 'msn.com',
    'icloud.com', 'me.com', 'mac.com', 'aol.com', 'proton.me', 'protonmail.com', 'zoho.com', 'gmx.com', 'mail.com',
    'yandex.com', 'qq.com', '163.com', 'rediffmail.com',
}


def matching_organizations(email: str):
    """Current organizations whose domains cover `email`, best first (one
    the person already belongs to, then the earliest-ending deal last)."""
    if not email or '@' not in email:
        return []
    from django.utils import timezone

    today = timezone.localdate()
    current = Organization.objects.filter(
        is_active=True, start_date__lte=today, end_date__gte=today,
    ).select_related('plan').order_by('-end_date')
    return [org for org in current if org.matches_email(email)]


def organization_for(user):
    """The organization giving `user` access right now, or None. Takes a
    seat on first use."""
    if not user.is_authenticated or not user.email_confirmed_at:
        return None
    candidates = matching_organizations(user.email)
    if not candidates:
        return None
    member_of = set(OrganizationMember.objects.filter(
        user=user, organization__in=candidates,
    ).values_list('organization_id', flat=True))
    for org in candidates:
        if org.pk in member_of:
            return org
    for org in candidates:
        if _take_seat(org, user):
            return org
    return None


def _take_seat(org, user) -> bool:
    with transaction.atomic():
        locked = Organization.objects.select_for_update().get(pk=org.pk)
        if locked.seats is not None and locked.members.count() >= locked.seats:
            return False
        try:
            with transaction.atomic():
                OrganizationMember.objects.create(organization=locked, user=user)
        except IntegrityError:
            pass  # joined a moment ago in another request
    return True


def pending_organization_for(user):
    """An organization the user would get once they confirm their email —
    for a "confirm your email to read with <org>" prompt. None otherwise."""
    if not user.is_authenticated or user.email_confirmed_at:
        return None
    candidates = matching_organizations(user.email)
    return candidates[0] if candidates else None
