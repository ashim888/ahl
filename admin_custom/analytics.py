"""Analytics: one page per area instead of one page for everything.

    /editorial/analytics/                 Overview — the headline numbers of each area
    /editorial/analytics/readership/      page views, readers, top stories, sections
    /editorial/analytics/subscriptions/   new, trials, cancelled, lapsed, plans
    /editorial/analytics/ads/             impressions, clicks, CTR by zone and ad
    /editorial/analytics/newsletter/      sign-ups, unsubscribes, issues sent
    (/editorial/keywords/ — topics — has its own page, linked from the tabs.)

Every page shares one period (7/30/90 days, 12 months or a custom from–to)
and compares it with the period just before it, so each number answers
"how did we do, and is it better or worse?". Only dated events are counted
— no lifetime running totals mixed in with period figures. Charts group
by day (up to a month), week (up to ~4 months) or month (longer), so a long
period stays readable. Every page downloads as CSV (?export=csv) for the
same period and filters.

Money is shown to Editor-in-Chief/Admin only, as on the Revenue pages.
"""
import calendar
import csv
import datetime
import math
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from django_comments_xtd.models import XtdComment

from ads.models import AdEvent, AdSlot
from articles.models import Article, ArticleView, Bookmark
from billing.models import ArticlePurchase, Payment, PromoRedemption, SubscriptionPlan, UserSubscription
from billing.money import format_money
from newsletter.models import NewsletterIssue, Subscriber
from sections.models import Section
from users.decorators import role_required
from users.models import User

PRESETS = [(7, '7 days'), (30, '30 days'), (90, '90 days'), (365, '12 months')]
DEFAULT_PRESET = 30
MAX_CUSTOM_DAYS = 731

# Series colours (inline styles, so no Tailwind class has to exist for them).
VIOLET, EMERALD, ROSE, SKY, AMBER = '#7c3aed', '#059669', '#e11d48', '#0284c7', '#d97706'


# -- Period -------------------------------------------------------------------

def _midnight(day: datetime.date) -> datetime.datetime:
    """Local midnight starting `day` — explicit datetime ranges rather than
    `__date` lookups, which need MySQL's time-zone tables (see
    admin_custom/views.py _daily_counts)."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))


@dataclass(frozen=True)
class Bucket:
    """One chart column: days start..end inclusive."""
    start: datetime.date
    end: datetime.date
    label: str
    title: str

    @property
    def start_dt(self):
        return _midnight(self.start)

    @property
    def end_dt(self):
        return _midnight(self.end + datetime.timedelta(days=1))


@dataclass(frozen=True)
class Period:
    """Days start..end inclusive; `preset` is 7/30/90/365 or None (custom)."""
    start: datetime.date
    end: datetime.date
    preset: int | None = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def start_dt(self):
        return _midnight(self.start)

    @property
    def end_dt(self):
        """Exclusive upper bound: midnight after the last day."""
        return _midnight(self.end + datetime.timedelta(days=1))

    @property
    def previous(self) -> 'Period':
        end = self.start - datetime.timedelta(days=1)
        return Period(end - datetime.timedelta(days=self.days - 1), end)

    @property
    def label(self) -> str:
        if self.start.year == self.end.year:
            return f'{self.start:%b %-d} – {self.end:%b %-d, %Y}'
        return f'{self.start:%b %-d, %Y} – {self.end:%b %-d, %Y}'

    @property
    def query(self) -> str:
        if self.preset:
            return f'range={self.preset}'
        return f'from={self.start.isoformat()}&to={self.end.isoformat()}'

    def dt_filter(self, field: str) -> dict:
        return {f'{field}__gte': self.start_dt, f'{field}__lt': self.end_dt}

    def date_filter(self, field: str) -> dict:
        return {f'{field}__gte': self.start, f'{field}__lte': self.end}

    def buckets(self) -> list[Bucket]:
        """Days up to a month, weeks up to ~4 months, calendar months beyond."""
        out = []
        if self.days <= 31:
            day = self.start
            while day <= self.end:
                out.append(Bucket(day, day, f'{day:%b %-d}', f'{day:%a %b %-d}'))
                day += datetime.timedelta(days=1)
        elif self.days <= 124:
            day = self.start
            while day <= self.end:
                last = min(day + datetime.timedelta(days=6), self.end)
                out.append(Bucket(day, last, f'{day:%b %-d}', f'Week of {day:%b %-d} – {last:%b %-d}'))
                day = last + datetime.timedelta(days=1)
        else:
            day = self.start
            while day <= self.end:
                last = min(day.replace(day=calendar.monthrange(day.year, day.month)[1]), self.end)
                label = f'{day:%b}' if self.start.year == self.end.year else f'{day:%b %y}'
                title = f'{day:%B %Y}' + ('' if day.day == 1 and last.day == calendar.monthrange(day.year, day.month)[1]
                                          else f' ({day:%b %-d} – {last:%b %-d})')
                out.append(Bucket(day, last, label, title))
                day = last + datetime.timedelta(days=1)
        return out

    @property
    def granularity(self) -> str:
        return 'day' if self.days <= 31 else 'week' if self.days <= 124 else 'month'


def parse_period(params) -> tuple[Period, str]:
    """The period from ?range= or ?from=&to=; returns (period, error)."""
    today = timezone.localdate()
    raw_from, raw_to = params.get('from'), params.get('to')
    if raw_from or raw_to:
        try:
            start = datetime.date.fromisoformat(raw_from or '')
            end = datetime.date.fromisoformat(raw_to or '')
        except ValueError:
            return _preset(DEFAULT_PRESET, today), 'Pick both a start and an end date.'
        if start > end:
            start, end = end, start
        end = min(end, today)
        if start > end:
            return _preset(DEFAULT_PRESET, today), 'That period is in the future.'
        if (end - start).days + 1 > MAX_CUSTOM_DAYS:
            start = end - datetime.timedelta(days=MAX_CUSTOM_DAYS - 1)
        return Period(start, end), ''
    try:
        preset = int(params.get('range', DEFAULT_PRESET))
    except (TypeError, ValueError):
        preset = DEFAULT_PRESET
    if preset not in dict(PRESETS):
        preset = DEFAULT_PRESET
    return _preset(preset, today), ''


def _preset(days: int, today: datetime.date) -> Period:
    return Period(today - datetime.timedelta(days=days - 1), today, days)


# -- Numbers --------------------------------------------------------------------

def change(current, previous, *, up_is_good: bool = True) -> dict:
    """A figure with its change against the previous period."""
    current, previous = current or 0, previous or 0
    if previous:
        pct = round((current - previous) / previous * 100)
    else:
        pct = None
    direction = 'up' if current > previous else 'down' if current < previous else 'flat'
    good = None if direction == 'flat' else (direction == 'up') == up_is_good
    return {'value': current, 'previous': previous, 'pct': pct, 'pct_abs': abs(pct) if pct is not None else None,
            'direction': direction, 'good': good, 'new': not previous and bool(current)}


def ctr(clicks, impressions):
    return round(clicks / impressions * 100, 2) if impressions else None


def share_rows(rows: list[dict], key: str = 'value') -> list[dict]:
    """Adds 'pct' (share of the total) and 'bar' (width vs the largest)."""
    total = sum(r[key] for r in rows) or 0
    top = max([r[key] for r in rows] + [1])
    for row in rows:
        row['pct'] = round(row[key] / total * 100) if total else 0
        row['bar'] = round(row[key] / top * 100)
    return rows


def count_series(queryset, field: str, buckets: list[Bucket], *, date_field: bool = False) -> list[int]:
    """Row count per bucket — one small indexed query each (at most ~31)."""
    values = []
    for b in buckets:
        if date_field:
            values.append(queryset.filter(**{f'{field}__gte': b.start, f'{field}__lte': b.end}).count())
        else:
            values.append(queryset.filter(**{f'{field}__gte': b.start_dt, f'{field}__lt': b.end_dt}).count())
    return values


def chart(buckets: list[Bucket], series: list[dict], *, unit: str = '') -> dict:
    """Chart data for includes/analytics_chart.html: grouped bars per
    bucket, one per series ({'name', 'color', 'values'}), scaled to the
    tallest bar, with every n-th label shown so long periods stay legible."""
    top = max([v for s in series for v in s['values']] + [0])
    step = max(1, math.ceil(len(buckets) / 10))
    columns = []
    for i, b in enumerate(buckets):
        bars = [{'value': s['values'][i], 'color': s['color'], 'name': s['name'],
                 'pct': round(s['values'][i] / top * 100) if top else 0} for s in series]
        columns.append({
            'label': b.label, 'period': b.title, 'show_label': i % step == 0 or i == len(buckets) - 1 and len(buckets) <= 10,
            'title': f'{b.title}: ' + ' · '.join(f'{bar["value"]:,} {bar["name"].lower()}' for bar in bars),
            'bars': bars,
        })
    return {
        'columns': columns, 'top': top, 'mid': round(top / 2) if top > 1 else None, 'unit': unit,
        'series': [{'name': s['name'], 'color': s['color'], 'total': sum(s['values'])} for s in series],
        'empty': top == 0,
    }


def retention_note(period: Period) -> str:
    """Raw page-view and ad events are deleted after ANALYTICS_RETENTION_DAYS."""
    days = int(getattr(settings, 'ANALYTICS_RETENTION_DAYS', 400))
    oldest = timezone.localdate() - datetime.timedelta(days=days)
    if period.previous.start < oldest:
        return (f'Page views and ad events are kept for {days} days, so figures before {oldest:%b %-d, %Y} '
                'are incomplete.')
    return ''


# -- Base view ---------------------------------------------------------------------

@method_decorator(role_required(*User.EDITORIAL_ROLES), name='dispatch')
class AnalyticsPage(TemplateView):
    """Shared by every analytics page: the period, the tabs, CSV export."""

    tab = ''
    title = ''
    # Extra GET filters this page understands (kept in the period links).
    filter_params: tuple = ()

    def get(self, request, *args, **kwargs):
        self.period, self.period_error = parse_period(request.GET)
        self.show_money = request.user.is_senior_staff
        if request.GET.get('export') == 'csv':
            return self.export_csv()
        return super().get(request, *args, **kwargs)

    def filters(self) -> dict:
        return {name: self.request.GET.get(name, '') for name in self.filter_params if self.request.GET.get(name)}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.period
        filters = self.filters()
        extra = ''.join(f'&{k}={v}' for k, v in filters.items())
        context.update({
            'tab': self.tab, 'page_heading': self.title, 'period': period, 'previous': period.previous,
            'period_error': self.period_error, 'show_money': self.show_money, 'filters': filters,
            'filter_query': extra,
            'presets': [{'days': d, 'label': label, 'active': period.preset == d,
                         'url': f'?range={d}{extra}'} for d, label in PRESETS],
            'export_url': f'?{period.query}{extra}&export=csv',
        })
        context.update(self.data())
        return context

    def data(self) -> dict:
        return {}

    def csv_rows(self, data: dict) -> list[list]:
        return []

    def export_csv(self):
        data = self.data()
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="analytics-{self.tab}-{self.period.start}-to-{self.period.end}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([f'{self.title} — {self.period.label} (compared with {self.period.previous.label})'])
        for key, value in self.filters().items():
            writer.writerow([f'Filter: {key}', value])
        writer.writerow([])
        for row in self.csv_rows(data):
            writer.writerow(row)
        return response


def _kpi_rows(kpis: list[dict]) -> list[list]:
    rows = [['Measure', 'This period', 'Previous period', 'Change %']]
    for k in kpis:
        rows.append([k['label'], k['value'], k['previous'], '' if k['pct'] is None else k['pct']])
    return rows + [[]]


def display(value, fmt: str = 'number') -> str:
    """1234 → "1,234"; percent → "2.35%"; money → "Rs. 4,999"."""
    if fmt == 'money':
        return format_money(value)
    if fmt == 'percent':
        return f'{value:.2f}%'
    return f'{value:,}'


def _kpi(label: str, current, previous, *, hint: str = '', up_is_good: bool = True, fmt: str = 'number') -> dict:
    return {'label': label, 'hint': hint, 'fmt': fmt, 'display': display(current or 0, fmt),
            'previous_display': display(previous or 0, fmt), **change(current, previous, up_is_good=up_is_good)}


def _series_rows(c: dict, buckets: list[Bucket]) -> list[list]:
    rows = [['Period'] + [s['name'] for s in c['series']]]
    for b, col in zip(buckets, c['columns']):
        rows.append([b.title] + [bar['value'] for bar in col['bars']])
    return rows + [[]]


# -- Readership ---------------------------------------------------------------------

class ReadershipView(AnalyticsPage):
    template_name = 'admin_custom/analytics/readership.html'
    tab, title = 'readership', 'Readership'
    filter_params = ('section', 'type')

    def _views(self):
        views = ArticleView.objects.all()
        filters = self.filters()
        if filters.get('section', '').isdigit():
            section = int(filters['section'])
            views = views.filter(Q(article__section_id=section) | Q(article__section__parent_id=section))
        if filters.get('type'):
            views = views.filter(article__article_type=filters['type'])
        return views

    def _articles(self):
        articles = Article.objects.filter(status=Article.Status.PUBLISHED)
        filters = self.filters()
        if filters.get('section', '').isdigit():
            section = int(filters['section'])
            articles = articles.filter(Q(section_id=section) | Q(section__parent_id=section))
        if filters.get('type'):
            articles = articles.filter(article_type=filters['type'])
        return articles

    def data(self):
        period, previous = self.period, self.period.previous
        views = self._views()
        now_views, prev_views = views.filter(**period.dt_filter('viewed_at')), views.filter(**previous.dt_filter('viewed_at'))
        readers = lambda qs: qs.exclude(session_key='').values('session_key').distinct().count()  # noqa: E731
        articles = self._articles()
        published = articles.filter(**period.dt_filter('published_at')).count()
        published_prev = articles.filter(**previous.dt_filter('published_at')).count()
        bookmarks = Bookmark.objects.all()
        comments = XtdComment.objects.filter(content_type=ContentType.objects.get_for_model(Article),
                                             is_public=True, is_removed=False)
        if self.filters():
            bookmarks = bookmarks.filter(article__in=articles.values('pk'))
            comments = comments.filter(object_pk__in=[str(pk) for pk in articles.values_list('pk', flat=True)])

        view_count = now_views.count()
        kpis = [
            _kpi('Page views', view_count, prev_views.count(),
                 hint='Article pages opened by readers (staff excluded; a reload within a few minutes counts once).'),
            _kpi('Unique readers', readers(now_views), readers(prev_views),
                 hint='Different browsers that read at least one article.'),
            _kpi('Stories published', published, published_prev),
            _kpi('Saved to reading lists', bookmarks.filter(**period.dt_filter('bookmarked_at')).count(),
                 bookmarks.filter(**previous.dt_filter('bookmarked_at')).count()),
            _kpi('Reader comments', comments.filter(**period.dt_filter('submit_date')).count(),
                 comments.filter(**previous.dt_filter('submit_date')).count()),
        ]

        buckets = period.buckets()
        trend = chart(buckets, [{'name': 'Page views', 'color': VIOLET,
                                 'values': count_series(views, 'viewed_at', buckets)}])

        # Top stories in the period.
        top = list(now_views.values('article').annotate(
            views=Count('id'), readers=Count('session_key', distinct=True),
        ).order_by('-views')[:20])
        by_pk = Article.objects.select_related('section').in_bulk([row['article'] for row in top])
        saved = dict(bookmarks.filter(**period.dt_filter('bookmarked_at'))
                     .values_list('article').annotate(n=Count('id')).order_by())
        commented = dict(comments.filter(**period.dt_filter('submit_date'))
                         .values_list('object_pk').annotate(n=Count('id')).order_by())
        top_stories = []
        for row in top:
            article = by_pk.get(row['article'])
            if article is None:
                continue
            top_stories.append({
                'article': article, 'views': row['views'], 'readers': row['readers'],
                'saved': saved.get(article.pk, 0), 'comments': commented.get(str(article.pk), 0),
                'share': round(row['views'] / view_count * 100) if view_count else 0,
                'new': bool(article.published_at and article.published_at >= period.start_dt),
            })

        def breakdown(field, labels):
            rows = [{'label': labels.get(key, key) or 'No section', 'value': n}
                    for key, n in now_views.values_list(field).annotate(n=Count('id')).order_by('-n')]
            return share_rows(rows)

        sections = dict(Section.objects.values_list('pk', 'name'))
        return {
            'kpis': kpis, 'trend': trend, 'top_stories': top_stories,
            'by_section': breakdown('article__section', sections),
            'by_type': breakdown('article__article_type', dict(Article.ArticleType.choices)),
            'by_access': breakdown('article__access_type', dict(Article.AccessType.choices)),
            'section_choices': Section.objects.order_by('name').values_list('pk', 'name'),
            'type_choices': Article.ArticleType.choices,
            'retention_note': retention_note(period),
        }

    def csv_rows(self, data):
        rows = _kpi_rows(data['kpis']) + _series_rows(data['trend'], self.period.buckets())
        rows.append(['Top stories', 'Page views', 'Unique readers', 'Saved', 'Comments', 'Published'])
        for s in data['top_stories']:
            rows.append([s['article'].title, s['views'], s['readers'], s['saved'], s['comments'],
                         s['article'].published_at.date().isoformat() if s['article'].published_at else ''])
        for title, key in (('Section', 'by_section'), ('Story type', 'by_type'), ('Access', 'by_access')):
            rows += [[], [title, 'Page views', 'Share %']] + [[r['label'], r['value'], r['pct']] for r in data[key]]
        return rows


# -- Subscriptions --------------------------------------------------------------------

def _active_on(day: datetime.date):
    """Subscriptions giving access on `day` (cancelled ones excluded only
    once they were cancelled — older cancellations weren't timed)."""
    return UserSubscription.objects.filter(start_date__lte=day, end_date__gte=day).filter(
        Q(cancelled_at__isnull=True, status__in=[UserSubscription.Status.ACTIVE, UserSubscription.Status.EXPIRED])
        | Q(cancelled_at__gte=_midnight(day + datetime.timedelta(days=1))),
    )


def _lapsed(period: Period):
    """Paid subscriptions that ran out in the period with no follow-on
    subscription for the same reader — the people who didn't renew."""
    renewed = UserSubscription.objects.filter(
        user=OuterRef('user'), is_trial=False, end_date__gt=OuterRef('end_date'),
    ).exclude(pk=OuterRef('pk'))
    # end_date is the last day of access, so "ran out" means it's in the past.
    return (UserSubscription.objects.filter(is_trial=False, end_date__gte=period.start, end_date__lte=period.end,
                                            end_date__lt=timezone.localdate())
            .exclude(status=UserSubscription.Status.CANCELLED)
            .annotate(renewed=Exists(renewed)).filter(renewed=False))


class SubscriptionsView(AnalyticsPage):
    template_name = 'admin_custom/analytics/subscriptions.html'
    tab, title = 'subscriptions', 'Subscriptions'

    def data(self):
        period, previous, today = self.period, self.period.previous, timezone.localdate()
        paid = UserSubscription.objects.filter(is_trial=False)
        trials = UserSubscription.objects.filter(is_trial=True)
        cancelled = paid.filter(cancelled_at__isnull=False)

        active_now = _active_on(today).filter(is_trial=False)
        active_at_start = _active_on(period.start).filter(is_trial=False).count()
        lapsed, lapsed_prev = _lapsed(period).count(), _lapsed(previous).count()
        cancelled_now = cancelled.filter(**period.dt_filter('cancelled_at')).count()
        lost = lapsed + cancelled_now
        new_paid = paid.filter(**period.dt_filter('created_at')).count()

        trials_started = trials.filter(**period.dt_filter('created_at'))
        converted = trials_started.filter(Exists(paid.filter(user=OuterRef('user'), created_at__gt=OuterRef('created_at'))))
        trial_count = trials_started.count()

        kpis = [
            _kpi('New subscriptions', new_paid, paid.filter(**previous.dt_filter('created_at')).count(),
                 hint='Paid or staff-granted subscriptions started in the period (renewals included, trials not).'),
            _kpi('Free trials started', trial_count, trials.filter(**previous.dt_filter('created_at')).count()),
            _kpi('Cancelled', cancelled_now, cancelled.filter(**previous.dt_filter('cancelled_at')).count(),
                 up_is_good=False, hint='Cancelled by the reader, revoked by staff or refunded.'),
            _kpi('Didn’t renew', lapsed, lapsed_prev, up_is_good=False,
                 hint='Paid subscriptions that ran out in the period with no new one after them.'),
        ]

        buckets = period.buckets()
        new_series = count_series(paid, 'created_at', buckets)
        lost_series = [a + b for a, b in zip(count_series(cancelled, 'cancelled_at', buckets),
                                              [_lapsed(Period(b.start, b.end)).count() for b in buckets])]
        trend = chart(buckets, [
            {'name': 'Started', 'color': EMERALD, 'values': new_series},
            {'name': 'Lost', 'color': ROSE, 'values': lost_series},
        ])

        plans = []
        active_by_plan = dict(active_now.values_list('plan').annotate(n=Count('id')).order_by())
        new_by_plan = dict(paid.filter(**period.dt_filter('created_at')).values_list('plan').annotate(n=Count('id')).order_by())
        lost_by_plan = dict(_lapsed(period).values_list('plan').annotate(n=Count('id')).order_by())
        for pk, n in cancelled.filter(**period.dt_filter('cancelled_at')).values_list('plan').annotate(n=Count('id')).order_by():
            lost_by_plan[pk] = lost_by_plan.get(pk, 0) + n
        for plan in SubscriptionPlan.objects.order_by('-is_active', 'price'):
            row = {'plan': plan, 'active': active_by_plan.get(plan.pk, 0), 'new': new_by_plan.get(plan.pk, 0),
                   'lost': lost_by_plan.get(plan.pk, 0)}
            if row['active'] or row['new'] or row['lost'] or plan.is_active:
                plans.append(row)

        purchases = ArticlePurchase.objects.all()
        redemptions = PromoRedemption.objects.filter(**period.dt_filter('created_at'))
        data = {
            'kpis': kpis, 'trend': trend, 'plans': plans,
            'active_now': active_now.count(),
            'trials_active': _active_on(today).filter(is_trial=True).count(),
            'net_change': new_paid - lost,
            'churn_rate': round(lost / active_at_start * 100, 1) if active_at_start else None,
            'active_at_start': active_at_start,
            'trial_count': trial_count, 'trials_converted': converted.count(),
            'trial_conversion': round(converted.count() / trial_count * 100) if trial_count else None,
            'expiring_7': paid.filter(status=UserSubscription.Status.ACTIVE, end_date__gte=today,
                                      end_date__lte=today + datetime.timedelta(days=7)).count(),
            'expiring_30': paid.filter(status=UserSubscription.Status.ACTIVE, end_date__gte=today,
                                       end_date__lte=today + datetime.timedelta(days=30)).count(),
            'purchases': _kpi('Special articles bought', purchases.filter(**period.dt_filter('purchased_at')).count(),
                              purchases.filter(**previous.dt_filter('purchased_at')).count()),
            'top_codes': list(redemptions.values('code__code').annotate(n=Count('id')).order_by('-n')[:5]),
        }
        if self.show_money:
            def revenue(p, *kinds):
                return Payment.objects.filter(status=Payment.Status.SUCCESS, kind__in=kinds,
                                              **p.dt_filter('completed_at')).aggregate(t=Sum('subtotal'))['t'] or Decimal('0')
            kinds = (Payment.Kind.SUBSCRIPTION, Payment.Kind.INSTITUTIONAL)
            data['revenue'] = _kpi('Subscription revenue', revenue(period, *kinds), revenue(previous, *kinds), fmt='money',
                                   hint='Paid in the period, before VAT. Refunded payments not included.')
            data['purchase_revenue'] = _kpi('Special-article revenue', revenue(period, Payment.Kind.ARTICLE),
                                            revenue(previous, Payment.Kind.ARTICLE), fmt='money')
        return data

    def csv_rows(self, data):
        rows = _kpi_rows(data['kpis'] + [data['purchases']] + ([data['revenue'], data['purchase_revenue']]
                                                                if self.show_money else []))
        rows += [['Active paid subscriptions today', data['active_now']], ['Trials active today', data['trials_active']],
                 ['Net change in the period', data['net_change']],
                 ['Lost as % of those active at the start', '' if data['churn_rate'] is None else data['churn_rate']],
                 ['Trials converted to paid', data['trials_converted']], ['Ending in the next 30 days', data['expiring_30']], []]
        rows += _series_rows(data['trend'], self.period.buckets())
        rows.append(['Plan', 'Active today', 'Started in period', 'Lost in period'])
        rows += [[p['plan'].name, p['active'], p['new'], p['lost']] for p in data['plans']]
        return rows


# -- Ads -------------------------------------------------------------------------------

class AdsView(AnalyticsPage):
    template_name = 'admin_custom/analytics/ads.html'
    tab, title = 'ads', 'Ads'
    filter_params = ('zone',)

    def data(self):
        period, previous = self.period, self.period.previous
        zone = self.filters().get('zone', '')
        if zone not in AdSlot.Zone.values:
            zone = ''
        events = AdEvent.objects.filter(ad_slot__zone=zone) if zone else AdEvent.objects.all()
        impressions = events.filter(event_type=AdEvent.EventType.IMPRESSION)
        clicks = events.filter(event_type=AdEvent.EventType.CLICK)
        imp_now, imp_prev = impressions.filter(**period.dt_filter('occurred_at')).count(), impressions.filter(
            **previous.dt_filter('occurred_at')).count()
        clk_now, clk_prev = clicks.filter(**period.dt_filter('occurred_at')).count(), clicks.filter(
            **previous.dt_filter('occurred_at')).count()
        ctr_now, ctr_prev = ctr(clk_now, imp_now), ctr(clk_prev, imp_prev)
        kpis = [
            _kpi('Impressions', imp_now, imp_prev, hint='Times an ad was shown to a reader.'),
            _kpi('Clicks', clk_now, clk_prev),
            {**_kpi('Click-through rate', ctr_now or 0, ctr_prev or 0, fmt='percent'),
             'hint': 'Clicks ÷ impressions.' if imp_now else 'No impressions in this period.'},
        ]
        buckets = period.buckets()
        impressions_chart = chart(buckets, [{'name': 'Impressions', 'color': SKY,
                                             'values': count_series(impressions, 'occurred_at', buckets)}])
        clicks_chart = chart(buckets, [{'name': 'Clicks', 'color': AMBER,
                                        'values': count_series(clicks, 'occurred_at', buckets)}])

        in_period = Q(events__occurred_at__gte=period.start_dt, events__occurred_at__lt=period.end_dt)
        imp_q = in_period & Q(events__event_type=AdEvent.EventType.IMPRESSION)
        clk_q = in_period & Q(events__event_type=AdEvent.EventType.CLICK)
        ads = AdSlot.objects.filter(zone=zone) if zone else AdSlot.objects.all()
        ad_rows = []
        today = timezone.localdate()
        for ad in ads.annotate(imp=Count('events', filter=imp_q), clk=Count('events', filter=clk_q)).order_by('-imp', '-clk'):
            running = ad.is_active and ad.start_date <= today and (ad.end_date is None or ad.end_date >= today)
            if not (ad.imp or ad.clk or running):
                continue
            ad_rows.append({'ad': ad, 'impressions': ad.imp, 'clicks': ad.clk, 'ctr': ctr(ad.clk, ad.imp), 'running': running})
        zone_rows = []
        if not zone:
            by_zone = {row['zone']: row for row in AdSlot.objects.values('zone').annotate(
                imp=Count('events', filter=imp_q), clk=Count('events', filter=clk_q))}
            for value, label in AdSlot.Zone.choices:
                row = by_zone.get(value, {'imp': 0, 'clk': 0})
                zone_rows.append({'value': value, 'label': label, 'impressions': row['imp'], 'clicks': row['clk'],
                                  'ctr': ctr(row['clk'], row['imp'])})
            zone_rows = share_rows(sorted(zone_rows, key=lambda r: -r['impressions']), 'impressions')
        return {
            'kpis': kpis, 'impressions_chart': impressions_chart, 'clicks_chart': clicks_chart,
            'ad_rows': ad_rows, 'zone_rows': zone_rows, 'zone': zone,
            'zone_label': dict(AdSlot.Zone.choices).get(zone, ''), 'zone_choices': AdSlot.Zone.choices,
            'running_count': sum(1 for r in ad_rows if r['running']),
            'retention_note': retention_note(period),
        }

    def csv_rows(self, data):
        buckets = self.period.buckets()
        rows = _kpi_rows(data['kpis'])
        rows.append(['Period', 'Impressions', 'Clicks'])
        for b, i, c in zip(buckets, data['impressions_chart']['columns'], data['clicks_chart']['columns']):
            rows.append([b.title, i['bars'][0]['value'], c['bars'][0]['value']])
        rows += [[], ['Ad', 'Zone', 'Running', 'Impressions', 'Clicks', 'CTR %']]
        rows += [[r['ad'].sponsor_name, r['ad'].get_zone_display(), 'yes' if r['running'] else 'no', r['impressions'],
                  r['clicks'], '' if r['ctr'] is None else r['ctr']] for r in data['ad_rows']]
        if data['zone_rows']:
            rows += [[], ['Zone', 'Impressions', 'Clicks', 'CTR %']]
            rows += [[r['label'], r['impressions'], r['clicks'], '' if r['ctr'] is None else r['ctr']] for r in data['zone_rows']]
        return rows


# -- Newsletter --------------------------------------------------------------------------

class NewsletterView(AnalyticsPage):
    template_name = 'admin_custom/analytics/newsletter.html'
    tab, title = 'newsletter', 'Newsletter'

    def data(self):
        period, previous = self.period, self.period.previous
        subscribers = Subscriber.objects.all()
        joined = subscribers.filter(confirmed_at__isnull=False)
        left = subscribers.filter(status=Subscriber.Status.UNSUBSCRIBED, unsubscribed_at__isnull=False)
        signed_up = subscribers.filter(**period.dt_filter('subscribed_at'))
        joined_now = joined.filter(**period.dt_filter('confirmed_at')).count()
        left_now = left.filter(**period.dt_filter('unsubscribed_at')).count()
        issues = NewsletterIssue.objects.filter(sent_at__isnull=False)
        sent_now = issues.filter(**period.dt_filter('sent_at'))
        kpis = [
            _kpi('New subscribers', joined_now, joined.filter(**previous.dt_filter('confirmed_at')).count(),
                 hint='Confirmed their email address in the period.'),
            _kpi('Unsubscribed', left_now, left.filter(**previous.dt_filter('unsubscribed_at')).count(), up_is_good=False),
            _kpi('Issues sent', sent_now.count(), issues.filter(**previous.dt_filter('sent_at')).count()),
            _kpi('Emails delivered', sent_now.aggregate(t=Sum('recipient_count'))['t'] or 0,
                 issues.filter(**previous.dt_filter('sent_at')).aggregate(t=Sum('recipient_count'))['t'] or 0,
                 hint='Recipients of the issues sent in the period.'),
        ]
        buckets = period.buckets()
        trend = chart(buckets, [
            {'name': 'Joined', 'color': EMERALD, 'values': count_series(joined, 'confirmed_at', buckets)},
            {'name': 'Left', 'color': ROSE, 'values': count_series(left, 'unsubscribed_at', buckets)},
        ])
        sign_up_count = signed_up.count()
        confirmed_of_those = signed_up.filter(confirmed_at__isnull=False).count()
        return {
            'kpis': kpis, 'trend': trend,
            'confirmed_now': subscribers.filter(status=Subscriber.Status.CONFIRMED).count(),
            'net_change': joined_now - left_now,
            'sign_ups': sign_up_count, 'confirmed_of_sign_ups': confirmed_of_those,
            'confirm_rate': round(confirmed_of_those / sign_up_count * 100) if sign_up_count else None,
            'waiting': signed_up.filter(status=Subscriber.Status.PENDING).count(),
            'issues': list(sent_now.order_by('-sent_at')[:50]),
        }

    def csv_rows(self, data):
        rows = _kpi_rows(data['kpis'])
        rows += [['Confirmed subscribers today', data['confirmed_now']], ['Net change in the period', data['net_change']],
                 ['Signed up in the period', data['sign_ups']], ['…of whom confirmed', data['confirmed_of_sign_ups']], []]
        rows += _series_rows(data['trend'], self.period.buckets())
        rows.append(['Issue', 'Audience', 'Sent', 'Recipients'])
        rows += [[i.subject, i.get_audience_display(), timezone.localtime(i.sent_at).strftime('%Y-%m-%d %H:%M'),
                  i.recipient_count] for i in data['issues']]
        return rows


# -- Overview --------------------------------------------------------------------------

class OverviewView(AnalyticsPage):
    """One card per area, each with its headline figures, a small trend
    and a link to the full page — nothing here that isn't explained there."""

    template_name = 'admin_custom/analytics/overview.html'
    tab, title = 'overview', 'Analytics overview'

    def data(self):
        period, previous = self.period, self.period.previous
        buckets = period.buckets()

        def pair(qs, field):
            return qs.filter(**period.dt_filter(field)).count(), qs.filter(**previous.dt_filter(field)).count()

        def readers(p):
            return ArticleView.objects.filter(**p.dt_filter('viewed_at')).exclude(session_key='').values(
                'session_key').distinct().count()

        paid = UserSubscription.objects.filter(is_trial=False)
        impressions = AdEvent.objects.filter(event_type=AdEvent.EventType.IMPRESSION)
        clicks = AdEvent.objects.filter(event_type=AdEvent.EventType.CLICK)
        joined = Subscriber.objects.filter(confirmed_at__isnull=False)
        left = Subscriber.objects.filter(status=Subscriber.Status.UNSUBSCRIBED, unsubscribed_at__isnull=False)
        imp, clk = pair(impressions, 'occurred_at'), pair(clicks, 'occurred_at')
        lost_now = _lapsed(period).count() + paid.filter(**period.dt_filter('cancelled_at')).count()
        lost_prev = _lapsed(previous).count() + paid.filter(**previous.dt_filter('cancelled_at')).count()

        cards = [
            {'title': 'Readership', 'url': reverse('admin_custom:analytics_readership'), 'color': VIOLET,
             'kpis': [_kpi('Page views', *pair(ArticleView.objects.all(), 'viewed_at')),
                      _kpi('Unique readers', readers(period), readers(previous))],
             'chart': chart(buckets, [{'name': 'Page views', 'color': VIOLET,
                                       'values': count_series(ArticleView.objects.all(), 'viewed_at', buckets)}])},
            {'title': 'Subscriptions', 'url': reverse('admin_custom:analytics_subscriptions'), 'color': EMERALD,
             'kpis': [_kpi('New subscriptions', *pair(paid, 'created_at')),
                      _kpi('Lost', lost_now, lost_prev, up_is_good=False)],
             'note': f'{_active_on(timezone.localdate()).filter(is_trial=False).count():,} active today',
             'chart': chart(buckets, [{'name': 'Started', 'color': EMERALD,
                                       'values': count_series(paid, 'created_at', buckets)}])},
            {'title': 'Ads', 'url': reverse('admin_custom:analytics_ads'), 'color': SKY,
             'kpis': [_kpi('Impressions', *imp), _kpi('Clicks', *clk),
                      _kpi('Click-through rate', ctr(clk[0], imp[0]) or 0, ctr(clk[1], imp[1]) or 0, fmt='percent')],
             'chart': chart(buckets, [{'name': 'Impressions', 'color': SKY,
                                       'values': count_series(impressions, 'occurred_at', buckets)}])},
            {'title': 'Newsletter', 'url': reverse('admin_custom:analytics_newsletter'), 'color': AMBER,
             'kpis': [_kpi('New subscribers', *pair(joined, 'confirmed_at')),
                      _kpi('Unsubscribed', *pair(left, 'unsubscribed_at'), up_is_good=False)],
             'note': f'{Subscriber.objects.filter(status=Subscriber.Status.CONFIRMED).count():,} confirmed today',
             'chart': chart(buckets, [{'name': 'Joined', 'color': AMBER,
                                       'values': count_series(joined, 'confirmed_at', buckets)}])},
        ]
        if self.show_money:
            payments = Payment.objects.filter(status=Payment.Status.SUCCESS)

            def revenue(p):
                return payments.filter(**p.dt_filter('completed_at')).aggregate(t=Sum('subtotal'))['t'] or Decimal('0')
            cards.append({
                'title': 'Revenue', 'url': reverse('admin_custom:revenue'), 'color': EMERALD,
                'kpis': [_kpi('Revenue (before VAT)', revenue(period), revenue(previous), fmt='money'),
                         _kpi('Payments', *pair(payments, 'completed_at'))],
                'note': 'Subscriptions, special articles, training and institutions.',
            })
        return {'cards': cards}

    def csv_rows(self, data):
        rows = [['Area', 'Measure', 'This period', 'Previous period', 'Change %']]
        for card in data['cards']:
            for k in card['kpis']:
                rows.append([card['title'], k['label'], k['value'], k['previous'], '' if k['pct'] is None else k['pct']])
        return rows
