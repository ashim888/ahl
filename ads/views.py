import datetime
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import AdSlotForm
from .models import AdEvent, AdSettings, AdSlot
from .placements import PLACEMENTS
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
        q = self.request.GET.get('q')
        if zone:
            queryset = queryset.filter(zone=zone)
        if active == 'yes':
            queryset = queryset.filter(is_active=True)
        elif active == 'no':
            queryset = queryset.filter(is_active=False)
        if q:
            queryset = queryset.filter(sponsor_name__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['zones'] = AdSlot.Zone.choices
        context['selected_zone'] = self.request.GET.get('zone', '')
        context['selected_active'] = self.request.GET.get('active', '')
        context['selected_q'] = self.request.GET.get('q', '')
        context['placeholder_zones'] = AdSettings.get_solo().placeholder_zones
        return context


class AdSlotFormMixin:
    def get_success_url(self):
        return reverse('ads:manage_adslot_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The layout picture on the form (ads/placements.py): where each zone
        # shows, on which screens, its size, and the ads already running
        # there (drawn into the picture with their own image) — so an editor
        # sees the zone, and what's in it, before choosing it.
        today = timezone.localdate()
        running = (AdSlot.objects.filter(is_active=True, start_date__lte=today)
                   .filter(Q(end_date__isnull=True) | Q(end_date__gte=today)).order_by('-created_at'))
        if getattr(self, 'object', None) and self.object.pk:
            running = running.exclude(pk=self.object.pk)
        running_by_zone = {}
        for ad in running:
            running_by_zone.setdefault(ad.zone, []).append({
                'sponsor': ad.sponsor_name, 'image': ad.image.url if ad.image else '',
                'until': ad.end_date.strftime('%b %-d, %Y') if ad.end_date else '',
                'edit_url': reverse('ads:manage_adslot_update', args=[ad.pk]),
            })
        context['zone_info'] = {
            value: {'label': label, 'width': AdSlot.ZONE_DIMENSIONS[value][0],
                    'height': AdSlot.ZONE_DIMENSIONS[value][1], 'ads': running_by_zone.get(value, []),
                    'running': len(running_by_zone.get(value, [])), **PLACEMENTS[value]}
            for value, label in AdSlot.Zone.choices
        }
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
class AdSlotDeleteView(DeleteView):
    model = AdSlot
    template_name = 'ads/manage/adslot_confirm_delete.html'

    def get_success_url(self):
        return reverse('ads:manage_adslot_list')

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object.sponsor_name}" ad deleted.')
        return super().form_valid(form)


def _bucket_ad_events_by_day(events_queryset, window_days=30):
    """Buckets an AdEvent queryset into a day-by-day impressions/clicks
    series, pure Python — deliberately not a DB date-truncation query, see
    admin_custom/views.py's identical `_daily_counts` pattern and its
    comment on why `occurred_at__date=day` needs CONVERT_TZ() support this
    project doesn't assume is configured on the MySQL server. Shared by
    AdSlotAnalyticsView (one ad's day-by-day chart).
    """
    today = timezone.localdate()
    days = [today - datetime.timedelta(days=i) for i in range(window_days - 1, -1, -1)]
    window_start = timezone.make_aware(datetime.datetime.combine(days[0], datetime.time.min))

    counts_by_day = {day: {'impressions': 0, 'clicks': 0} for day in days}
    events = events_queryset.filter(occurred_at__gte=window_start).only('event_type', 'occurred_at')
    for event in events:
        bucket = counts_by_day.get(timezone.localtime(event.occurred_at).date())
        if bucket is None:
            continue
        if event.event_type == AdEvent.EventType.IMPRESSION:
            bucket['impressions'] += 1
        else:
            bucket['clicks'] += 1

    daily_stats = [{'label': day.strftime('%b %-d'), **counts_by_day[day]} for day in days]
    max_daily = max([d['impressions'] for d in daily_stats] + [1])
    for d in daily_stats:
        d['impressions_pct'] = round(d['impressions'] / max_daily * 100)
        d['clicks_pct'] = round(d['clicks'] / max_daily * 100)
    return daily_stats


def _window_totals(daily_stats):
    impressions = sum(d['impressions'] for d in daily_stats)
    clicks = sum(d['clicks'] for d in daily_stats)
    ctr = round(clicks / impressions * 100, 2) if impressions else None
    return {'window_impressions': impressions, 'window_clicks': clicks, 'window_ctr': ctr}


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AdSlotAnalyticsView(DetailView):
    """Per-ad day-by-day impressions/clicks/CTR, last 30 days — the list
    page only shows lifetime totals, which can't answer whether a specific
    sponsorship is trending up or down, or which days it actually ran.
    """

    model = AdSlot
    template_name = 'ads/manage/adslot_analytics.html'
    context_object_name = 'ad'

    WINDOW_DAYS = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        daily_stats = _bucket_ad_events_by_day(self.object.events.all(), self.WINDOW_DAYS)
        context['daily_stats'] = daily_stats
        context.update(_window_totals(daily_stats))
        return context


@role_required(*EDITORIAL_ROLES)
def ads_analytics_overview(request):
    """The sitewide ad numbers moved to Analytics → Ads
    (admin_custom/analytics.py AdsView), alongside the other areas and on
    the same period picker; old links and bookmarks land there."""
    query = {}
    zone = request.GET.get('filter_zone') or request.GET.get('zone')
    if zone in AdSlot.Zone.values:
        query['zone'] = zone
    days = request.GET.get('chart_days') or request.GET.get('filter_days')
    query['range'] = {'7': 7, '14': 30, '30': 30, '90': 90}.get(days or '', 30)
    return redirect(f"{reverse('admin_custom:analytics_ads')}?{urlencode(query)}")


@role_required(*EDITORIAL_ROLES)
@require_POST
def adslot_toggle_active(request, pk):
    ad = get_object_or_404(AdSlot, pk=pk)
    ad.is_active = not ad.is_active
    ad.save(update_fields=['is_active'])
    messages.success(request, f'"{ad.sponsor_name}" is now {"active" if ad.is_active else "inactive"}.')
    return redirect('ads:manage_adslot_list')


@role_required(*EDITORIAL_ROLES)
@require_POST
def ad_settings_update_placeholder_zones(request):
    """Per-zone switch (AdSettings.placeholder_zones) for what an unsold
    zone shows a reader — an "Advertise Here" placeholder, or nothing (the
    default). Was a single sitewide boolean; a chronically-unsold zone and
    a reliably-sold one don't need the same treatment. See ads_tags.py:ad_slot.
    """
    zones = [zone for zone in request.POST.getlist('placeholder_zones') if zone in AdSlot.Zone.values]
    settings_row = AdSettings.get_solo()
    settings_row.placeholder_zones = zones
    settings_row.save(update_fields=['placeholder_zones'])
    messages.success(request, f'"Advertise Here" placeholders updated for {len(zones)} zone(s).')
    return redirect('ads:manage_adslot_list')
