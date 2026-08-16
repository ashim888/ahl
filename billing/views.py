from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import GrantPurchaseForm, GrantSubscriptionForm, SubscriptionPlanForm
from .models import ArticlePurchase, SubscriptionPlan, UserSubscription

# Plans are visible/editable to any editorial staff, same as Article CRUD.
# Granting/revoking actual paid access is a bigger deal — restricted to
# senior staff (EiC/Admin), the same boundary StaffManage uses.
EDITORIAL_ROLES = User.EDITORIAL_ROLES
SENIOR_STAFF_ROLES = User.SENIOR_STAFF_ROLES


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
    """Every grant, active or not — the record of who currently has (or
    had) subscriber access, since there's no self-serve checkout yet.
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
        response = super().form_valid(form)
        messages.success(
            self.request,
            f'Granted "{form.instance.plan.name}" to {form.instance.user.email}, '
            f'active through {form.instance.end_date}.',
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
