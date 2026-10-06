"""Readers: /redeem/ and /redeem/<CODE>/ — start a free trial, or keep a
discount code for checkout (billing/promotions.py). Staff: promo codes under
/manage/billing/promos/ (Editor-in-Chief/Admin, like the rest of billing)."""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView
from django_ratelimit.decorators import ratelimit

from users.decorators import role_required
from users.models import User

from . import promotions
from .forms import PromoCodeForm
from .models import PromoCode


@ratelimit(key='ip', rate='30/m', method='POST', block=True)
def redeem(request, code=''):
    """Enter a code (or arrive with one in the link). A trial code shows the
    offer and a "Start free trial" button; a discount code is kept for
    checkout and the reader is sent to what it applies to."""
    text = (request.POST.get('code') or code or '').strip().upper()
    promo = promotions.find(text) if text else None
    if text and promo is None:
        messages.error(request, _('We don’t recognise that code — check the spelling.'))
        return render(request, 'billing/redeem.html', {'typed': text})
    if promo is None:
        return render(request, 'billing/redeem.html', {})
    problem = None
    if request.user.is_authenticated:
        try:
            if promo.is_trial:
                promotions.check_common(promo, request.user)
                if promotions.has_ever_subscribed(request.user):
                    raise promotions.PromoError(_('Free trials are for people who haven’t subscribed before.'))
            else:
                promotions.check_common(promo, request.user)
        except promotions.PromoError as exc:
            problem = str(exc)
    elif not promo.is_active:
        problem = _('This code is no longer active.')
    if not promo.is_trial and not problem:
        request.session[promotions.SESSION_KEY] = promo.code
        messages.success(request, _('Code %(code)s saved — it’s applied when you check out.') % {'code': promo.code})
        if promo.applies_to_subscriptions:
            return redirect('billing:plan_browse')
        if promo.applies_to_courses:
            return redirect('training:course_list')
        return redirect('articles:home')
    return render(request, 'billing/redeem.html', {'promo': promo, 'problem': problem})


@login_required
@require_POST
def start_trial(request, code):
    promo = get_object_or_404(PromoCode, code=code.upper())
    try:
        subscription = promotions.redeem_trial(promo, request.user)
    except promotions.PromoError as exc:
        messages.error(request, str(exc))
        return redirect('billing:redeem_code', code=promo.code)
    messages.success(request, _('Your free trial has started — full access until %(date)s. Nothing renews automatically.') % {
        'date': subscription.end_date.strftime('%-d %B %Y')})
    return redirect('articles:home')


# -- Staff ---------------------------------------------------------------

@method_decorator(role_required(*User.SENIOR_STAFF_ROLES), name='dispatch')
class PromoListView(ListView):
    model = PromoCode
    template_name = 'billing/manage/promo_list.html'
    context_object_name = 'codes'
    paginate_by = 50

    def get_queryset(self):
        queryset = PromoCode.objects.select_related('trial_plan')
        kind = self.request.GET.get('kind', '')
        if kind:
            queryset = queryset.filter(kind=kind)
        q = self.request.GET.get('q', '').strip()
        if q:
            queryset = queryset.filter(code__icontains=q) | queryset.filter(campaign__icontains=q) | \
                queryset.filter(partner_name__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for code in context['codes']:
            code.stats = promotions.report(code)
        context['kinds'] = PromoCode.Kind.choices
        return context


class PromoFormMixin:
    model = PromoCode
    form_class = PromoCodeForm
    template_name = 'billing/manage/promo_form.html'

    def get_success_url(self):
        return reverse('billing:manage_promo_list')


@method_decorator(role_required(*User.SENIOR_STAFF_ROLES), name='dispatch')
class PromoCreateView(PromoFormMixin, CreateView):
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        copies = form.make_copies(self.object, self.request.user)
        if copies:
            messages.success(self.request, f'{self.object.code} saved, plus {len(copies)} single-use copies.')
        else:
            messages.success(self.request, f'{self.object.code} saved.')
        return response


@method_decorator(role_required(*User.SENIOR_STAFF_ROLES), name='dispatch')
class PromoUpdateView(PromoFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stats'] = promotions.report(self.object)
        context['redemptions'] = self.object.redemptions.select_related('user', 'payment')[:200]
        context['share_url'] = self.request.build_absolute_uri(reverse('billing:redeem_code', args=[self.object.code]))
        return context

    def form_valid(self, form):
        messages.success(self.request, f'{form.instance.code} saved.')
        return super().form_valid(form)


@role_required(*User.SENIOR_STAFF_ROLES)
def promo_export(request, pk):
    """Every use of a code, for partner reports."""
    code = get_object_or_404(PromoCode, pk=pk)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="promo-{code.code}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Date', 'Reader', 'Email', 'Used on', 'Discount (before VAT)', 'Paid (incl. VAT)', 'Receipt'])
    for row in code.redemptions.select_related('user', 'payment'):
        writer.writerow([
            f'{row.created_at:%Y-%m-%d}', row.user.get_full_name(), row.user.email, row.item, row.discount_amount,
            row.payment.amount if row.payment else '0.00', row.payment.receipt_number if row.payment else '',
        ])
    return response
