import datetime
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django_ratelimit.decorators import ratelimit

from articles.models import Article
from users.decorators import role_required
from users.models import User

from . import fonepay, payments
from .access import user_has_active_subscription, user_has_purchased_article
from .forms import GrantPurchaseForm, GrantSubscriptionForm, OrganizationForm, SubscriptionPlanForm
from .gateway import charge_safely
from . import org_views
from .models import ArticlePurchase, Organization, OrganizationMember, Payment, SubscriptionPlan, UserSubscription
from .money import format_money, vat_breakdown
from .services import next_start_date, paid_through

logger = logging.getLogger(__name__)

# Plans are visible/editable to any editorial staff, same as Article CRUD.
# Granting/revoking actual paid access is a bigger deal — restricted to
# senior staff (EiC/Admin), the same boundary StaffManage uses.
EDITORIAL_ROLES = User.EDITORIAL_ROLES
SENIOR_STAFF_ROLES = User.SENIOR_STAFF_ROLES

# How soon "expiring soon" means, on the subscriptions manage list and the
# dashboard KPI — no renewal reminder existed at all before this; a fixed
# window is a reasonable start without adding a configurable setting no one
# asked for yet.
EXPIRING_SOON_WINDOW_DAYS = 7


# -- Public — plan browsing & self-serve checkout ---------------------------
# No real payment gateway is wired in yet (billing/gateway.py — StubGateway
# always succeeds). These are real, self-serve flows a reader can complete
# without editorial help; only the actual money-movement step is stubbed.

def build_comparison_matrix(plans):
    """One row per PlanFeature referenced by any of `plans`, each row's
    `included` list aligned index-for-index with `plans` — used by both the
    pricing page and a single plan's detail page so the two never show
    inconsistent feature sets. `plans` must have `.features` prefetched.
    """
    feature_ids_seen = []
    features_by_id = {}
    for plan in plans:
        for feature in plan.features.all():
            if feature.id not in features_by_id:
                features_by_id[feature.id] = feature
                feature_ids_seen.append(feature.id)
    ordered_features = sorted(features_by_id.values(), key=lambda f: (f.order, f.id))

    matrix = []
    for feature in ordered_features:
        included = [feature.id in {f.id for f in plan.features.all()} for plan in plans]
        matrix.append({'feature': feature, 'included': included})
    return matrix


def _buyer_pan(request):
    """(pan, error) from the checkout's optional PAN box."""
    try:
        return payments.clean_pan(request.POST.get('buyer_pan', '')), None
    except ValueError as exc:
        return '', str(exc)


def _next_path(request) -> str:
    """The page to come back to after paying (e.g. the article whose paywall
    sent the reader here), carried as ?next= / a hidden field."""
    return payments.safe_return_path(request.POST.get('next') or request.GET.get('next') or '')


def _subscription_context(request) -> dict:
    """What the plan pages need to know about the reader's current access."""
    user = request.user
    if not user.is_authenticated:
        return {
            'already_subscribed': False, 'paid_through': None, 'renewal_starts': None, 'organization': None,
            'next_path': _next_path(request),
        }
    from .institutions import organization_for

    current_end = paid_through(user)
    return {
        'already_subscribed': user_has_active_subscription(user),
        'paid_through': current_end,
        'renewal_starts': current_end + datetime.timedelta(days=1) if current_end else None,
        'organization': organization_for(user) if not current_end else None,
        'next_path': _next_path(request),
    }


class PlanBrowseView(ListView):
    model = SubscriptionPlan
    template_name = 'billing/plan_browse.html'
    context_object_name = 'plans'

    def get_queryset(self):
        return SubscriptionPlan.objects.filter(is_active=True).order_by('price').prefetch_related('features')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_subscription_context(self.request))
        context['comparison_matrix'] = build_comparison_matrix(context['plans'])
        context['contact_email'] = settings.JOURNAL_CONTACT_EMAIL
        return context


class PlanDetailView(DetailView):
    """The "why this plan" page — full feature checklist for this plan plus
    a comparison table against every other active plan, before a reader
    commits to checkout.
    """

    model = SubscriptionPlan
    template_name = 'billing/plan_detail.html'
    context_object_name = 'plan'

    def get_queryset(self):
        return SubscriptionPlan.objects.filter(is_active=True).prefetch_related('features')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plan_features'] = self.object.features.order_by('order', 'id')
        context.update(_subscription_context(self.request))
        all_plans = list(
            SubscriptionPlan.objects.filter(is_active=True).order_by('price').prefetch_related('features'),
        )
        context['plans'] = all_plans
        context['comparison_matrix'] = build_comparison_matrix(all_plans)
        context['contact_email'] = settings.JOURNAL_CONTACT_EMAIL
        return context


@login_required
def subscribe_checkout(request, pk):
    """Buy a plan — or renew/switch early: a reader who already has one
    gets the new period from the day after their current one ends."""
    plan = get_object_or_404(SubscriptionPlan, pk=pk, is_active=True)
    if plan.plan_type == SubscriptionPlan.PlanType.INSTITUTIONAL:
        messages.info(request, f'Institutional plans are set up with your organization — email {settings.JOURNAL_CONTACT_EMAIL}.')
        return redirect('billing:plan_detail', pk=plan.pk)

    next_path = _next_path(request)
    starts = next_start_date(request.user)
    ends = starts + datetime.timedelta(days=plan.duration_days)
    description = f'Subscription — {plan.name}'

    buyer_pan, pan_error = _buyer_pan(request) if request.method == 'POST' else ('', None)
    if pan_error:
        messages.error(request, pan_error)
    elif request.method == 'POST' and payments.uses_fonepay():
        return _start_fonepay(
            request, kind=Payment.Kind.SUBSCRIPTION, price=plan.price, description=description, plan=plan,
            return_path=next_path, buyer_pan=buyer_pan,
        )
    elif request.method == 'POST':
        subtotal, vat, total = vat_breakdown(plan.price)
        result = charge_safely(request.user, total, description)
        if result.success:
            payment = payments.record_paid_payment(
                user=request.user, kind=Payment.Kind.SUBSCRIPTION, plan=plan, price=plan.price,
                description=description, gateway=Payment.Gateway.STUB, return_path=next_path, buyer_pan=buyer_pan,
            )
            Payment.objects.filter(pk=payment.pk).update(gateway_trace_id=result.reference[:64])
            messages.success(request, f'Subscribed to "{plan.name}" — active until {ends:%-d %b %Y}.')
            return redirect(payments.success_url(payment))
        messages.error(request, result.error or 'Payment failed — please try again.')

    return render(request, 'billing/subscribe_checkout.html', {
        'plan': plan, 'starts': starts, 'ends': ends, 'is_renewal': starts > timezone.localdate(),
        'next_path': next_path, 'buyer_pan': request.POST.get('buyer_pan') or payments.last_buyer_pan(request.user),
    })


@login_required
def purchase_checkout(request, slug):
    article = get_object_or_404(
        Article, slug=slug, status=Article.Status.PUBLISHED, access_type=Article.AccessType.PAY_PER_ARTICLE,
    )

    if user_has_active_subscription(request.user) or user_has_purchased_article(request.user, article):
        return redirect('articles:article_detail', slug=article.slug)

    description = f'Article — {article.title}'
    buyer_pan, pan_error = _buyer_pan(request) if request.method == 'POST' else ('', None)
    if pan_error:
        messages.error(request, pan_error)
    elif request.method == 'POST' and payments.uses_fonepay():
        return _start_fonepay(
            request, kind=Payment.Kind.ARTICLE, price=article.price, description=description, article=article,
            buyer_pan=buyer_pan,
        )
    elif request.method == 'POST':
        subtotal, vat, total = vat_breakdown(article.price)
        result = charge_safely(request.user, total, description)
        if result.success:
            payment = payments.record_paid_payment(
                user=request.user, kind=Payment.Kind.ARTICLE, article=article, price=article.price,
                description=description, gateway=Payment.Gateway.STUB, buyer_pan=buyer_pan,
            )
            Payment.objects.filter(pk=payment.pk).update(gateway_trace_id=result.reference[:64])
            messages.success(request, f'Purchased "{article.title}".')
            return redirect('articles:article_detail', slug=article.slug)
        messages.error(request, result.error or 'Payment failed — please try again.')

    return render(request, 'billing/purchase_checkout.html', {
        'article': article, 'buyer_pan': request.POST.get('buyer_pan') or payments.last_buyer_pan(request.user),
    })


def _start_fonepay(request, **payment_kwargs):
    """Shared by every checkout: create the Fonepay payment and send the
    reader to the payment page, or back with an error if Fonepay is down."""
    try:
        payment = payments.start_payment(request.user, **payment_kwargs)
    except fonepay.FonepayError:
        logger.exception('Could not start Fonepay payment for %s', request.user)
        messages.error(request, 'We couldn\'t start the payment with Fonepay right now. Please try again in a moment.')
        return redirect(request.get_full_path())
    return redirect('billing:payment_page', reference=payment.reference)


@login_required
def account(request):
    """The reader's billing page: what they have, until when, and every
    payment with its receipt."""
    from .institutions import organization_for, pending_organization_for

    user = request.user
    today = timezone.localdate()
    subscriptions = list(
        UserSubscription.objects.filter(user=user).select_related('plan').order_by('-end_date')[:20],
    )
    current = next((s for s in subscriptions if s.is_currently_active), None)
    upcoming = [
        s for s in subscriptions
        if s.status == UserSubscription.Status.ACTIVE and s.start_date > today
    ]
    current_end = paid_through(user)
    renew_plan = current.plan if current and current.plan.is_active else None
    # Cancellable within SUBSCRIPTION_CANCEL_DAYS of paying (Refunds policy).
    paid_by_reference = {
        p.reference: p for p in Payment.objects.filter(
            user=user, kind=Payment.Kind.SUBSCRIPTION, reference__in=[s.payment_reference for s in subscriptions if s.payment_reference],
        )
    }
    for subscription in subscriptions:
        payment = paid_by_reference.get(subscription.payment_reference)
        subscription.cancel_payment = payment if payment and payments.can_cancel(payment) else None
        subscription.cancel_deadline = payments.cancellation_deadline(payment) if subscription.cancel_payment else None
    return render(request, 'billing/account.html', {
        'current': current,
        'upcoming': sorted(upcoming, key=lambda s: s.start_date),
        'past': [s for s in subscriptions if s is not current and s not in upcoming][:10],
        'paid_through': current_end,
        'days_left': (current_end - today).days if current_end else None,
        'renew_plan': renew_plan,
        'organization': organization_for(user),
        'pending_organization': pending_organization_for(user),
        'managed_organizations': org_views.managed_organizations(user),
        'purchases': ArticlePurchase.objects.filter(user=user).select_related('article')[:50],
        'payments': Payment.objects.filter(
            user=user, status__in=(Payment.Status.SUCCESS, Payment.Status.REFUNDED),
        ).order_by('-completed_at')[:50],
        'open_payments': Payment.objects.filter(
            user=user, status=Payment.Status.PENDING, expires_at__gt=timezone.now(),
        ).order_by('-created_at'),
        'expiring_soon_days': EXPIRING_SOON_WINDOW_DAYS,
        'contact_email': settings.JOURNAL_CONTACT_EMAIL,
        'refunds_pending': Payment.objects.filter(user=user, refund_requested_at__isnull=False, status=Payment.Status.SUCCESS),
        'cancel_days': settings.SUBSCRIPTION_CANCEL_DAYS,
    })


@login_required
@require_POST
def subscription_cancel(request, reference):
    """The reader cancels a subscription within the cancellation window."""
    payment = get_object_or_404(Payment, reference=reference, user=request.user, kind=Payment.Kind.SUBSCRIPTION)
    try:
        payments.cancel_subscription(payment)
    except payments.CancellationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Cancelled. Your refund of {format_money(payment.amount)} is on its way — we’ve emailed you.')
    return redirect('billing:account')


@login_required
def receipt(request, reference):
    """A printable receipt — the payer's own, or any for senior staff."""
    payment = get_object_or_404(
        Payment.objects.select_related('user', 'organization', 'plan', 'article', 'course'),
        reference=reference, status__in=(Payment.Status.SUCCESS, Payment.Status.REFUNDED),
    )
    is_staff_view = request.user.is_senior_staff
    if payment.user_id != request.user.pk and not is_staff_view:
        raise Http404
    return render(request, 'billing/receipt.html', {
        'payment': payment, 'vat_rate': settings.VAT_RATE.normalize(), 'is_staff_view': is_staff_view,
        'seller': {
            'legal_name': settings.BUSINESS_LEGAL_NAME, 'pan': settings.BUSINESS_PAN,
            'address': settings.BUSINESS_ADDRESS, 'email': settings.JOURNAL_CONTACT_EMAIL,
        },
    })


@login_required
def payment_page(request, reference):
    """Pay with Fonepay: QR to scan (desktop) or bank-app buttons (mobile),
    live status over Fonepay's WebSocket, and a server-confirmed result."""
    payment = get_object_or_404(Payment, reference=reference, user=request.user)
    if payment.status == Payment.Status.PENDING:
        payment = payments.verify_payment(payment) if payment.is_expired else payment
    if payment.status == Payment.Status.SUCCESS:
        messages.success(request, f'Payment received — {payment.description}.')
        return redirect(payments.success_url(payment))
    banks = []
    if payment.status == Payment.Status.PENDING:
        try:
            banks = fonepay.bank_list()
        except fonepay.FonepayError:
            logger.warning('Could not load Fonepay bank list')
    return render(request, 'billing/payment_page.html', {
        'payment': payment, 'banks': banks, 'retry_url': payments.retry_url(payment),
        'seconds_left': max(int((payment.expires_at - timezone.now()).total_seconds()), 0),
    })


# At most one call to Fonepay per payment in this many seconds, however
# often the page (or a script) asks — the page polls every 5s and also
# checks on every WebSocket message.
PAYMENT_CHECK_MIN_INTERVAL_SECONDS = 4


@login_required
@ratelimit(key='user', rate='30/m', block=False)
def payment_check(request, reference):
    """JSON status for the payment page — always confirmed with Fonepay's
    status API server-side, never trusted from the browser. Throttled so it
    can't be used to hammer Fonepay: over 30 checks a minute gets a 429, and
    within PAYMENT_CHECK_MIN_INTERVAL_SECONDS of the last real check the
    saved status is returned without asking Fonepay again."""
    payment = get_object_or_404(Payment, reference=reference, user=request.user)
    if getattr(request, 'limited', False):
        return JsonResponse({'status': payment.status, 'redirect': '', 'retry_after': 10}, status=429)
    # cache.add is atomic: only the first request in each window gets True.
    if payment.status == Payment.Status.PENDING and cache.add(
        f'billing:payment-check:{payment.pk}', 1, PAYMENT_CHECK_MIN_INTERVAL_SECONDS,
    ):
        payment = payments.verify_payment(payment)
    return JsonResponse({
        'status': payment.status,
        'redirect': payments.success_url(payment) if payment.status == Payment.Status.SUCCESS else '',
    })


@method_decorator(role_required(*User.SENIOR_STAFF_ROLES), name='dispatch')
class PlanListView(ListView):
    model = SubscriptionPlan
    template_name = 'billing/manage/plan_list.html'
    context_object_name = 'plans'
    paginate_by = 30

    def get_queryset(self):
        # Newest-created first for editorial management — distinct from
        # PlanBrowseView above, which orders by price on purpose (a reader
        # comparing plans wants cheapest-first, not most-recently-added).
        queryset = SubscriptionPlan.objects.order_by('-created_at')
        plan_type = self.request.GET.get('plan_type')
        active = self.request.GET.get('active')
        if plan_type:
            queryset = queryset.filter(plan_type=plan_type)
        if active == 'yes':
            queryset = queryset.filter(is_active=True)
        elif active == 'no':
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plan_types'] = SubscriptionPlan.PlanType.choices
        context['selected_plan_type'] = self.request.GET.get('plan_type', '')
        context['selected_active'] = self.request.GET.get('active', '')
        return context


class PlanFormMixin:
    def get_success_url(self):
        return reverse('billing:manage_plan_list')


@method_decorator(role_required(*User.SENIOR_STAFF_ROLES), name='dispatch')
class PlanCreateView(PlanFormMixin, CreateView):
    model = SubscriptionPlan
    form_class = SubscriptionPlanForm
    template_name = 'billing/manage/plan_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.name}" created.')
        return super().form_valid(form)


@method_decorator(role_required(*User.SENIOR_STAFF_ROLES), name='dispatch')
class PlanUpdateView(PlanFormMixin, UpdateView):
    model = SubscriptionPlan
    form_class = SubscriptionPlanForm
    template_name = 'billing/manage/plan_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.name}" updated.')
        return super().form_valid(form)


@role_required(*User.SENIOR_STAFF_ROLES)
@require_POST
def plan_toggle_active(request, pk):
    plan = get_object_or_404(SubscriptionPlan, pk=pk)
    plan.is_active = not plan.is_active
    plan.save(update_fields=['is_active'])
    messages.success(request, f'"{plan.name}" is now {"active" if plan.is_active else "inactive"}.')
    return redirect('billing:manage_plan_list')


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class SubscriptionListView(ListView):
    """Every grant, active or not — self-serve checkout (subscribe_checkout,
    above) creates rows here too, alongside manually-granted ones.
    """

    model = UserSubscription
    template_name = 'billing/manage/subscription_list.html'
    context_object_name = 'subscriptions'
    paginate_by = 30

    def get_queryset(self):
        queryset = UserSubscription.objects.select_related('user', 'plan').order_by('-created_at')
        status = self.request.GET.get('status')
        plan_id = self.request.GET.get('plan')
        if status:
            queryset = queryset.filter(status=status)
        if plan_id:
            queryset = queryset.filter(plan_id=plan_id)
        if self.request.GET.get('expiring') == '1':
            today = timezone.localdate()
            queryset = queryset.filter(
                status=UserSubscription.Status.ACTIVE,
                end_date__gte=today, end_date__lte=today + datetime.timedelta(days=EXPIRING_SOON_WINDOW_DAYS),
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = UserSubscription.Status.choices
        context['plans'] = SubscriptionPlan.objects.order_by('name')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_plan'] = self.request.GET.get('plan', '')
        context['selected_expiring'] = self.request.GET.get('expiring', '')
        context['expiring_soon_window_days'] = EXPIRING_SOON_WINDOW_DAYS
        context['expiring_soon_cutoff'] = timezone.localdate() + datetime.timedelta(days=EXPIRING_SOON_WINDOW_DAYS)
        return context


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class SubscriptionGrantView(CreateView):
    model = UserSubscription
    form_class = GrantSubscriptionForm
    template_name = 'billing/manage/subscription_grant_form.html'
    success_url = reverse_lazy('billing:manage_subscription_list')

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'recorded_by': self.request.user}

    def form_valid(self, form):
        # form.save() (GrantSubscriptionForm.save) returns the real created
        # row via billing.services.start_subscription — end_date isn't a form
        # field, so form.instance never has it; self.object (set by
        # super().form_valid()) is the actual saved subscription.
        response = super().form_valid(form)
        messages.success(
            self.request,
            f'Granted "{self.object.plan.name}" to {self.object.user.email}, '
            f'active through {self.object.end_date}.',
        )
        return response


@role_required(*SENIOR_STAFF_ROLES)
@require_POST
def subscription_revoke(request, pk):
    subscription = get_object_or_404(UserSubscription, pk=pk)
    subscription.status = UserSubscription.Status.CANCELLED
    subscription.save(update_fields=['status'])
    messages.success(request, f'Subscription for {subscription.user.email} cancelled.')
    return redirect('billing:manage_subscription_list')


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class PurchaseListView(ListView):
    model = ArticlePurchase
    template_name = 'billing/manage/purchase_list.html'
    context_object_name = 'purchases'
    paginate_by = 30

    def get_queryset(self):
        queryset = ArticlePurchase.objects.select_related('user', 'article').order_by('-purchased_at')
        article_id = self.request.GET.get('article')
        if article_id:
            queryset = queryset.filter(article_id=article_id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['articles'] = Article.objects.filter(
            purchases__isnull=False,
        ).distinct().order_by('title')
        context['selected_article'] = self.request.GET.get('article', '')
        return context


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class PurchaseGrantView(CreateView):
    model = ArticlePurchase
    form_class = GrantPurchaseForm
    template_name = 'billing/manage/purchase_grant_form.html'
    success_url = reverse_lazy('billing:manage_purchase_list')

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'recorded_by': self.request.user}

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request, f'Recorded {form.instance.user.email}\'s purchase of "{form.instance.article.title}".',
        )
        return response


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class PaymentListView(ListView):
    """Every payment — the money ledger behind the revenue screens, with
    filters for what needs a look (failed, still pending)."""

    model = Payment
    template_name = 'billing/manage/payment_list.html'
    context_object_name = 'payments'
    paginate_by = 40

    def get_queryset(self):
        queryset = Payment.objects.select_related('user', 'organization').order_by('-created_at')
        for field in ('status', 'kind', 'gateway'):
            value = self.request.GET.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        if self.request.GET.get('attention') == '1':
            queryset = queryset.exclude(attention='')
        q = self.request.GET.get('q', '').strip()
        if q:
            queryset = queryset.filter(
                Q(reference__icontains=q) | Q(receipt_number__icontains=q) | Q(credit_note_number__icontains=q) | Q(user__email__icontains=q)
                | Q(organization__name__icontains=q) | Q(description__icontains=q) | Q(gateway_trace_id__icontains=q),
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = Payment.Status.choices
        context['kinds'] = Payment.Kind.choices
        context['gateways'] = Payment.Gateway.choices
        for field in ('status', 'kind', 'gateway', 'q', 'attention'):
            context[f'selected_{field}'] = self.request.GET.get(field, '')
        context['attention_count'] = Payment.objects.exclude(attention='').count()
        return context


@role_required(*SENIOR_STAFF_ROLES)
@require_POST
def payment_refund(request, reference):
    """Record a full refund already made outside the site, and take back
    the access it bought (billing/payments.py refund_payment)."""
    payment = get_object_or_404(Payment, reference=reference)
    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, 'Say why it was refunded — it goes on the credit note record.')
    else:
        try:
            with transaction.atomic():
                payment = payments.refund_payment(payment, by=request.user, reason=reason)
        except payments.RefundError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'Refund recorded as {payment.credit_note_number}; access removed and the payer emailed.')
    return redirect('billing:receipt', reference=payment.reference)


@role_required(*SENIOR_STAFF_ROLES)
@require_POST
def payment_clear_attention(request, reference):
    payment = get_object_or_404(Payment, reference=reference)
    Payment.objects.filter(pk=payment.pk).update(attention='')
    messages.success(request, f'{payment.reference} marked as handled.')
    return redirect(f"{reverse('billing:manage_payment_list')}?attention=1")


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class OrganizationListView(ListView):
    model = Organization
    template_name = 'billing/manage/organization_list.html'
    context_object_name = 'organizations'

    def get_queryset(self):
        return Organization.objects.select_related('plan').annotate(member_count=Count('members')).order_by(
            '-is_active', 'name',
        )


class OrganizationFormMixin:
    model = Organization
    form_class = OrganizationForm
    template_name = 'billing/manage/organization_form.html'
    success_url = reverse_lazy('billing:manage_organization_list')

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            received = form.cleaned_data.get('amount_received')
            if received:
                payments.record_paid_payment(
                    organization=self.object, kind=Payment.Kind.INSTITUTIONAL, plan=self.object.plan,
                    total_paid=received, description=f'Institutional subscription — {self.object.name}',
                    gateway=Payment.Gateway.MANUAL, recorded_by=self.request.user, grant=False,
                )
        messages.success(self.request, f'"{self.object.name}" saved.')
        return response


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class OrganizationCreateView(OrganizationFormMixin, CreateView):
    def get_initial(self):
        institutional = SubscriptionPlan.objects.filter(plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL).first()
        return {
            'plan': institutional, 'start_date': timezone.localdate(),
            'end_date': timezone.localdate() + datetime.timedelta(days=365),
        }


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class OrganizationUpdateView(OrganizationFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from . import org_reports

        start, end = org_reports.month_bounds(timezone.localdate())
        usage = org_reports.summary(self.object, start, end)
        context['members'] = self.object.members.select_related('user').order_by('removed_at', 'user__first_name')[:200]
        context['usage'] = usage
        context['last_month'] = org_reports.previous_month()[0]
        context['org_payments'] = self.object.payments.order_by('-created_at')
        return context


@role_required(*SENIOR_STAFF_ROLES)
@require_POST
def organization_send_report(request, pk):
    """Email last month's usage report to the organization now (it also
    goes out by itself on the 1st)."""
    from . import org_reports

    organization = get_object_or_404(Organization, pk=pk)
    if org_reports.send_report(organization):
        messages.success(request, f'Usage report for {organization.name} sent.')
    else:
        messages.error(request, 'Not sent — the organization has no contact email or managers, or the email failed.')
    return redirect('billing:manage_organization_update', pk=organization.pk)


@role_required(*SENIOR_STAFF_ROLES)
@require_POST
def organization_member_manager(request, pk, member_pk):
    """Staff: let a member run (or stop running) the organization dashboard."""
    organization = get_object_or_404(Organization, pk=pk)
    member = get_object_or_404(OrganizationMember, pk=member_pk, organization=organization, removed_at__isnull=True)
    member.is_manager = not member.is_manager
    member.save(update_fields=['is_manager'])
    messages.success(request, f"{member.user.email} {'can now' if member.is_manager else 'can no longer'} manage the dashboard.")
    return redirect('billing:manage_organization_update', pk=organization.pk)
