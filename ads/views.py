import datetime

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import AdSlotForm
from .models import AdEvent, AdSlot
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
        queryset = AdSlot.objects.order_by('-created_at')
        zone = self.request.GET.get('zone')
        active = self.request.GET.get('active')
        if zone:
            queryset = queryset.filter(zone=zone)
        if active == 'yes':
            queryset = queryset.filter(is_active=True)
        elif active == 'no':
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['zones'] = AdSlot.Zone.choices
        context['selected_zone'] = self.request.GET.get('zone', '')
        context['selected_active'] = self.request.GET.get('active', '')
        # Zone-level totals — a single ad's CTR (shown per-row) doesn't
        # answer "is the homepage or the sidebar performing better overall",
        # which is the question that actually informs where to sell more
        # sponsorships. Computed over all ads, not just this page, so
        # pagination doesn't skew it.
        zone_rows = AdSlot.objects.values('zone').annotate(
            impressions=Count('events', filter=Q(events__event_type=AdEvent.EventType.IMPRESSION)),
            clicks=Count('events', filter=Q(events__event_type=AdEvent.EventType.CLICK)),
        )
        zone_stats_by_value = {row['zone']: row for row in zone_rows}
        zone_stats = []
        for value, label in AdSlot.Zone.choices:
            row = zone_stats_by_value.get(value, {'impressions': 0, 'clicks': 0})
            impressions, clicks = row['impressions'], row['clicks']
            zone_stats.append({
                'label': label,
                'impressions': impressions,
                'clicks': clicks,
                'ctr': round(clicks / impressions * 100, 2) if impressions else None,
            })
        context['zone_stats'] = zone_stats
        return context


class AdSlotFormMixin:
    def get_success_url(self):
        return reverse('ads:manage_adslot_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Cheat-sheet on the create/edit form — the Zone select's label
        # already states one zone's required size, but an editor picking a
        # zone still needs to know it *before* choosing/cropping an image,
        # not just get an error after uploading the wrong size.
        context['zone_dimensions'] = [
            (label, *AdSlot.ZONE_DIMENSIONS[value]) for value, label in AdSlot.Zone.choices
        ]
        return context


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


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AdSlotAnalyticsView(DetailView):
    """Per-ad day-by-day impressions/clicks/CTR, last 30 days — the list
    page only shows lifetime totals, which can't answer whether a specific
    sponsorship is trending up or down, or which days it actually ran.
    Bucketed in Python (not a DB date-truncation query) deliberately — see
    admin_custom/views.py's identical daily_stats pattern and its comment on
    why `occurred_at__date=day` needs CONVERT_TZ() support this project
    doesn't assume is configured on the MySQL server.
    """

    model = AdSlot
    template_name = 'ads/manage/adslot_analytics.html'
    context_object_name = 'ad'

    WINDOW_DAYS = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        days = [today - datetime.timedelta(days=i) for i in range(self.WINDOW_DAYS - 1, -1, -1)]
        window_start = timezone.make_aware(datetime.datetime.combine(days[0], datetime.time.min))

        counts_by_day = {day: {'impressions': 0, 'clicks': 0} for day in days}
        events = self.object.events.filter(occurred_at__gte=window_start).only('event_type', 'occurred_at')
        for event in events:
            bucket = counts_by_day.get(timezone.localtime(event.occurred_at).date())
            if bucket is None:
                continue
            if event.event_type == AdEvent.EventType.IMPRESSION:
                bucket['impressions'] += 1
            else:
                bucket['clicks'] += 1

        daily_stats = [
            {'label': day.strftime('%b %-d'), **counts_by_day[day]} for day in days
        ]
        max_daily = max([d['impressions'] for d in daily_stats] + [1])
        for d in daily_stats:
            d['impressions_pct'] = round(d['impressions'] / max_daily * 100)
            d['clicks_pct'] = round(d['clicks'] / max_daily * 100)
        context['daily_stats'] = daily_stats
        context['window_impressions'] = sum(d['impressions'] for d in daily_stats)
        context['window_clicks'] = sum(d['clicks'] for d in daily_stats)
        context['window_ctr'] = (
            round(context['window_clicks'] / context['window_impressions'] * 100, 2)
            if context['window_impressions'] else None
        )
        return context


@role_required(*EDITORIAL_ROLES)
@require_POST
def adslot_toggle_active(request, pk):
    ad = get_object_or_404(AdSlot, pk=pk)
    ad.is_active = not ad.is_active
    ad.save(update_fields=['is_active'])
    messages.success(request, f'"{ad.sponsor_name}" is now {"active" if ad.is_active else "inactive"}.')
    return redirect('ads:manage_adslot_list')
