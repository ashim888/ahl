from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import AdSlotForm
from .models import AdSlot
from .services import record_click

# House-ad management is editorial content work, same boundary as Article/
# Training CRUD — not the money-sensitive tier billing's subscription grants
# use (EiC/Admin only). Editors arrange sponsorships directly; this screen
# just enters the creative.
EDITORIAL_ROLES = User.EDITORIAL_ROLES


def ad_click(request, pk):
    """Tracked-redirect, same pattern as articles:article_download —
    counts a click, then sends the reader on to the sponsor's page.
    """
    ad = get_object_or_404(AdSlot, pk=pk)
    record_click(ad)
    return redirect(ad.link_url)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AdSlotListView(ListView):
    model = AdSlot
    template_name = 'ads/manage/adslot_list.html'
    context_object_name = 'ad_slots'
    paginate_by = 30

    def get_queryset(self):
        return AdSlot.objects.order_by('-created_at')


class AdSlotFormMixin:
    def get_success_url(self):
        return reverse('ads:manage_adslot_list')


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AdSlotCreateView(AdSlotFormMixin, CreateView):
    model = AdSlot
    form_class = AdSlotForm
    template_name = 'ads/manage/adslot_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.sponsor_name}" ad created.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AdSlotUpdateView(AdSlotFormMixin, UpdateView):
    model = AdSlot
    form_class = AdSlotForm
    template_name = 'ads/manage/adslot_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.sponsor_name}" ad updated.')
        return super().form_valid(form)


@role_required(*EDITORIAL_ROLES)
@require_POST
def adslot_toggle_active(request, pk):
    ad = get_object_or_404(AdSlot, pk=pk)
    ad.is_active = not ad.is_active
    ad.save(update_fields=['is_active'])
    messages.success(request, f'"{ad.sponsor_name}" is now {"active" if ad.is_active else "inactive"}.')
    return redirect('ads:manage_adslot_list')
