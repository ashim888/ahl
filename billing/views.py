from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from articles.models import Article
from users.decorators import role_required
from users.models import User

from .access import user_has_active_subscription, user_has_purchased_article
from .forms import GrantPurchaseForm, GrantSubscriptionForm, SubscriptionPlanForm
from .gateway import get_gateway
from .models import ArticlePurchase, SubscriptionPlan, UserSubscription
from .services import record_purchase, start_subscription

# Plans are visible/editable to any editorial staff, same as Article CRUD.
# Granting/revoking actual paid access is a bigger deal — restricted to
# senior staff (EiC/Admin), the same boundary StaffManage uses.
EDITORIAL_ROLES = User.EDITORIAL_ROLES
SENIOR_STAFF_ROLES = User.SENIOR_STAFF_ROLES


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


class PlanBrowseView(ListView):
    model = SubscriptionPlan
    template_name = 'billing/plan_browse.html'
    context_object_name = 'plans'

    def get_queryset(self):
        return SubscriptionPlan.objects.filter(is_active=True).order_by('price').prefetch_related('features')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['already_subscribed'] = (
            self.request.user.is_authenticated and user_has_active_subscription(self.request.user)
        )
        context['comparison_matrix'] = build_comparison_matrix(context['plans'])
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
        context['already_subscribed'] = (
            self.request.user.is_authenticated and user_has_active_subscription(self.request.user)
        )
        all_plans = list(
            SubscriptionPlan.objects.filter(is_active=True).order_by('price').prefetch_related('features'),
        )
        context['plans'] = all_plans
        context['comparison_matrix'] = build_comparison_matrix(all_plans)
        return context


@login_required
def subscribe_checkout(request, pk):
    plan = get_object_or_404(SubscriptionPlan, pk=pk, is_active=True)

    if user_has_active_subscription(request.user):
        messages.info(request, "You already have an active subscription.")
        return redirect('billing:plan_browse')

    if request.method == 'POST':
        result = get_gateway().charge(
            request.user, plan.price, f'Subscription — {plan.name}',
        )
        if result.success:
            start_subscription(request.user, plan, payment_reference=result.reference)
            messages.success(request, f'Subscribed to "{plan.name}". Enjoy full access.')
            return redirect('users:profile')
        messages.error(request, result.error or 'Payment failed — please try again.')

    return render(request, 'billing/subscribe_checkout.html', {'plan': plan})


@login_required
def purchase_checkout(request, slug):
    article = get_object_or_404(
        Article, slug=slug, status=Article.Status.PUBLISHED, access_type=Article.AccessType.PAY_PER_ARTICLE,
    )

    if user_has_active_subscription(request.user) or user_has_purchased_article(request.user, article):
        return redirect('articles:article_detail', slug=article.slug)

    if request.method == 'POST':
        result = get_gateway().charge(request.user, article.price, f'Article — {article.title}')
        if result.success:
            record_purchase(request.user, article, article.price, payment_reference=result.reference)
            messages.success(request, f'Purchased "{article.title}".')
            return redirect('articles:article_detail', slug=article.slug)
        messages.error(request, result.error or 'Payment failed — please try again.')

    return render(request, 'billing/purchase_checkout.html', {'article': article})


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class PlanListView(ListView):
    model = SubscriptionPlan
    template_name = 'billing/manage/plan_list.html'
    context_object_name = 'plans'

    def get_queryset(self):
        return SubscriptionPlan.objects.order_by('price')


class PlanFormMixin:
    def get_success_url(self):
        return reverse('billing:manage_plan_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
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


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
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


@role_required(*EDITORIAL_ROLES)
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
        return UserSubscription.objects.select_related('user', 'plan').order_by('-created_at')


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class SubscriptionGrantView(CreateView):
    model = UserSubscription
    form_class = GrantSubscriptionForm
    template_name = 'billing/manage/subscription_grant_form.html'
    success_url = reverse_lazy('billing:manage_subscription_list')

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
        return ArticlePurchase.objects.select_related('user', 'article').order_by('-purchased_at')


@method_decorator(role_required(*SENIOR_STAFF_ROLES), name='dispatch')
class PurchaseGrantView(CreateView):
    model = ArticlePurchase
    form_class = GrantPurchaseForm
    template_name = 'billing/manage/purchase_grant_form.html'
    success_url = reverse_lazy('billing:manage_purchase_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request, f'Recorded {form.instance.user.email}\'s purchase of "{form.instance.article.title}".',
        )
        return response
