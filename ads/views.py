import datetime

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from users.decorators import role_required
from users.models import User

from .forms import AdSlotForm
from .models import AdEvent, AdSettings, AdSlot
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
        context['ad_placeholder_enabled'] = AdSettings.get_solo().show_placeholder_when_empty
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


def _bucket_ad_events_by_day(events_queryset, window_days=30):
    """Buckets an AdEvent queryset into a day-by-day impressions/clicks
    series, pure Python — deliberately not a DB date-truncation query, see
    admin_custom/views.py's identical `_daily_counts` pattern and its
    comment on why `occurred_at__date=day` needs CONVERT_TZ() support this
    project doesn't assume is configured on the MySQL server. Shared by
    AdSlotAnalyticsView (one ad's events) and AdSlotAnalyticsOverviewView
    (every ad's events) so the bucketing itself isn't duplicated between
    a per-ad chart and a sitewide one.
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


# Shared by every date-range control on the Ad Analytics page (the sitewide
# chart, and the filterable zone/ad panel below it) — a fixed preset list,
# not a free date picker, since "how far back" is the only thing anyone's
# actually asked to adjust here so far.
WINDOW_DAY_CHOICES = [7, 14, 30, 90]
DEFAULT_WINDOW_DAYS = 7


def _parse_window_days(raw_value):
    try:
        days = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    return days if days in WINDOW_DAY_CHOICES else DEFAULT_WINDOW_DAYS


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


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class AdSlotAnalyticsOverviewView(TemplateView):
    """Sitewide ad performance — split out from AdSlotListView, which used
    to mix a zone-level summary grid into the same page as the searchable,
    filterable, paginated ad list. Two different jobs ("what's the current
    ad inventory" vs. "how is it performing"), now two different pages.

    Two independent date-range controls, not one shared control, since they
    answer different questions: `chart_days` (GET) drives the sitewide
    "every ad, every zone" chart at the top; `filter_days` (GET), alongside
    `filter_zone`, drives the filterable panel below it — an always-shown
    per-zone table, or (once a specific zone is picked) a per-ad-in-that-
    zone table plus its own chart scoped to just that zone. Changing one
    control doesn't reset the other — both live in one <form> in the
    template so a GET submit carries every control's current value along.
    """

    template_name = 'ads/manage/adslot_analytics_overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        chart_days = _parse_window_days(self.request.GET.get('chart_days'))
        daily_stats = _bucket_ad_events_by_day(AdEvent.objects.all(), chart_days)
        context['daily_stats'] = daily_stats
        context['chart_days'] = chart_days
        context.update(_window_totals(daily_stats))

        context['all_time_impressions'] = AdSlot.objects.aggregate(total=Sum('impression_count'))['total'] or 0
        context['all_time_clicks'] = AdSlot.objects.aggregate(total=Sum('click_count'))['total'] or 0
        context['all_time_ctr'] = (
            round(context['all_time_clicks'] / context['all_time_impressions'] * 100, 2)
            if context['all_time_impressions'] else None
        )

        context['window_day_choices'] = WINDOW_DAY_CHOICES
        context['zones'] = AdSlot.Zone.choices
        filter_zone = self.request.GET.get('filter_zone', '')
        filter_days = _parse_window_days(self.request.GET.get('filter_days'))
        context['filter_zone'] = filter_zone
        context['filter_zone_label'] = dict(AdSlot.Zone.choices).get(filter_zone) if filter_zone else None
        context['filter_days'] = filter_days

        today = timezone.localdate()
        filter_window_start = timezone.make_aware(
            datetime.datetime.combine(today - datetime.timedelta(days=filter_days - 1), datetime.time.min),
        )
        impressions_in_window = Q(events__event_type=AdEvent.EventType.IMPRESSION, events__occurred_at__gte=filter_window_start)
        clicks_in_window = Q(events__event_type=AdEvent.EventType.CLICK, events__occurred_at__gte=filter_window_start)

        if filter_zone:
            # One row per ad in the selected zone — this is where "top ads"
            # went: picking a zone here shows exactly that, scoped and
            # windowed, rather than an always-shown, never-filtered sitewide
            # top-5 sitting on the page whether or not anyone wants it right now.
            ads_in_zone = AdSlot.objects.filter(zone=filter_zone).annotate(
                window_impressions=Count('events', filter=impressions_in_window),
                window_clicks=Count('events', filter=clicks_in_window),
            ).order_by('-window_clicks', '-window_impressions')
            context['performance_rows'] = [
                {
                    'label': ad.sponsor_name,
                    'sub_label': ad.get_zone_display(),
                    'impressions': ad.window_impressions,
                    'clicks': ad.window_clicks,
                    'ctr': round(ad.window_clicks / ad.window_impressions * 100, 2) if ad.window_impressions else None,
                    'url': reverse('ads:manage_adslot_analytics', args=[ad.pk]),
                }
                for ad in ads_in_zone
            ]
            filtered_events = AdEvent.objects.filter(ad_slot__zone=filter_zone)
            context['filtered_daily_stats'] = _bucket_ad_events_by_day(filtered_events, filter_days)
        else:
            # No zone picked — one row per zone (impressions/clicks/CTR
            # within the selected window). A compact table, not the
            # previous always-shown 2-column card grid, is most of what
            # "covering too much of the page" was about.
            zone_rows = AdSlot.objects.values('zone').annotate(
                impressions=Count('events', filter=impressions_in_window),
                clicks=Count('events', filter=clicks_in_window),
            )
            zone_rows_by_value = {row['zone']: row for row in zone_rows}
            context['performance_rows'] = [
                {
                    'label': label,
                    'sub_label': None,
                    'impressions': zone_rows_by_value.get(value, {}).get('impressions', 0),
                    'clicks': zone_rows_by_value.get(value, {}).get('clicks', 0),
                    'ctr': (
                        round(zone_rows_by_value[value]['clicks'] / zone_rows_by_value[value]['impressions'] * 100, 2)
                        if zone_rows_by_value.get(value, {}).get('impressions') else None
                    ),
                    'url': f"{reverse('ads:manage_ads_analytics')}?filter_zone={value}",
                }
                for value, label in AdSlot.Zone.choices
            ]
            # No chart here — it would just repeat the sitewide one above.
            # A chart only appears once a specific zone narrows it to
            # something the top chart doesn't already show.
            context['filtered_daily_stats'] = None
        return context


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
def ad_settings_toggle_placeholder(request):
    """Site-wide switch (AdSettings, singleton) for what an unsold zone
    shows a reader — an "Advertise Here" placeholder, or nothing (the
    previous, still-default behavior). See ads_tags.py:ad_slot.
    """
    settings_row = AdSettings.get_solo()
    settings_row.show_placeholder_when_empty = not settings_row.show_placeholder_when_empty
    settings_row.save(update_fields=['show_placeholder_when_empty'])
    state = 'on' if settings_row.show_placeholder_when_empty else 'off'
    messages.success(request, f'"Advertise Here" placeholders for empty ad zones are now {state}.')
    return redirect('ads:manage_adslot_list')
