"""Aggregations behind the editorial Keyword Analytics pages
(KeywordAnalyticsView / KeywordAnalyticsDetailView / keyword_analytics_csv_export
in admin_custom/views.py), built on articles.KeywordEvent.

Day/hour bucketing happens in the database (GROUP BY), so a page load reads
a few hundred aggregate rows rather than every event in the window — at
real traffic a 90-day window is millions of impression rows. The catch is
time zones: a named-zone conversion (CONVERT_TZ to 'Asia/Kathmandu') needs
MySQL time-zone tables this project doesn't assume are loaded (see
admin_custom/views.py:_daily_counts). Instead each timestamp is shifted by
the site's current UTC offset inside the query and then grouped as UTC,
which needs no tables. That's exact for TIME_ZONE = Asia/Kathmandu (+05:45,
no daylight saving); a DST zone would be off by an hour around transitions.
"""
import datetime

from django.db.models import Count, DateTimeField, ExpressionWrapper, F, Q
from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncDate
from django.utils import timezone

from articles.models import Article, Keyword, KeywordEvent

WINDOW_DAY_CHOICES = [7, 14, 30, 90]
DEFAULT_WINDOW_DAYS = 30

# Below this many impressions a keyword's CTR is noise (1 view + 1 click =
# "100%") — such rows still show their CTR, greyed out, but sort after every
# keyword with enough data when ranking by CTR, and never make the
# "Highest reader interest" list.
MIN_IMPRESSIONS_FOR_CTR_RANK = 20

# Violet-500-ish, matching admin_custom/views.py:TYPE_CHART_COLORS[0] and the
# dashboard's bar charts. Heatmap cells use it at varying alpha via an inline
# style, so no per-intensity Tailwind classes are needed in the compiled CSS.
HEATMAP_RGB = '124, 111, 234'

WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

SORT_CHOICES = {
    'clicks': 'Most clicked',
    'impressions': 'Most seen',
    'ctr': 'Highest click-through',
    'articles': 'Most articles',
    'followers': 'Most followers',
    'name': 'Name (A–Z)',
}
DEFAULT_SORT = 'clicks'


def parse_window_days(raw_value) -> int:
    """Validates a ?days= query value against WINDOW_DAY_CHOICES."""
    try:
        days = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    return days if days in WINDOW_DAY_CHOICES else DEFAULT_WINDOW_DAYS


def window_start_for(days: int) -> datetime.datetime:
    """Local midnight at the start of a `days`-long window ending today."""
    first_day = timezone.localdate() - datetime.timedelta(days=days - 1)
    return timezone.make_aware(datetime.datetime.combine(first_day, datetime.time.min))


def ctr(clicks: int, impressions: int) -> float | None:
    """Click-through rate as a percentage (2dp); None with no impressions —
    same convention as ads.AdSlot.ctr.
    """
    if not impressions:
        return None
    return round(clicks / impressions * 100, 2)


def _heat_style(count: int, max_count: int) -> tuple[str, bool]:
    """Inline background style for a heatmap cell, plus whether the cell is
    dark enough to need light text.
    """
    if not count or not max_count:
        return '', False
    alpha = round(0.12 + 0.88 * count / max_count, 2)
    return f'background-color: rgba({HEATMAP_RGB}, {alpha});', alpha > 0.55


def _with_local_time(queryset):
    """Annotates `local_ts`: occurred_at shifted to the site's local time
    (see module docstring), for grouping with tzinfo=UTC below.
    """
    offset = timezone.localtime().utcoffset() or datetime.timedelta(0)
    return queryset.annotate(
        local_ts=ExpressionWrapper(F('occurred_at') + offset, output_field=DateTimeField()),
    )


UTC = datetime.timezone.utc


def keyword_rows(window_start: datetime.datetime, query: str = '', sort: str = DEFAULT_SORT) -> list[dict]:
    """One row per Keyword: published-article count, followers, and
    impressions/clicks/CTR within the window. Sorted in Python — the CTR
    sort needs the low-data rule above, and the keyword table is small
    (editor-coined tags, not user-generated volume).
    """
    keywords = Keyword.objects.annotate(
        article_count=Count('articles', filter=Q(articles__status=Article.Status.PUBLISHED), distinct=True),
        follower_count=Count('followers', distinct=True),
    )
    if query:
        keywords = keywords.filter(name__icontains=query)

    event_counts = {
        row['keyword']: row
        for row in KeywordEvent.objects.filter(occurred_at__gte=window_start)
        .values('keyword')
        .annotate(
            impressions=Count('id', filter=Q(event_type=KeywordEvent.EventType.IMPRESSION)),
            clicks=Count('id', filter=Q(event_type=KeywordEvent.EventType.CLICK)),
        )
        .order_by()
    }

    rows = []
    for keyword in keywords:
        counts = event_counts.get(keyword.pk, {})
        impressions = counts.get('impressions', 0)
        clicks = counts.get('clicks', 0)
        rows.append({
            'keyword': keyword,
            'article_count': keyword.article_count,
            'follower_count': keyword.follower_count,
            'impressions': impressions,
            'clicks': clicks,
            'ctr': ctr(clicks, impressions),
            'low_data': impressions < MIN_IMPRESSIONS_FOR_CTR_RANK,
        })

    if sort == 'name':
        rows.sort(key=lambda r: r['keyword'].name.lower())
    elif sort == 'ctr':
        rows.sort(key=lambda r: (not r['low_data'], r['ctr'] or 0, r['clicks']), reverse=True)
    elif sort in ('impressions', 'articles', 'followers'):
        field = {'impressions': 'impressions', 'articles': 'article_count', 'followers': 'follower_count'}[sort]
        rows.sort(key=lambda r: (r[field], r['clicks']), reverse=True)
    else:
        rows.sort(key=lambda r: (r['clicks'], r['impressions']), reverse=True)
    return rows


def weekday_hour_heatmap(events_queryset) -> dict:
    """Click counts on a 7 (Mon–Sun) × 24 (local hour) grid — when readers
    actually click keywords. `events_queryset` should already be limited to
    clicks in the window (and, on the detail page, to one keyword).
    """
    grid = [[0] * 24 for _ in range(7)]
    buckets = (
        _with_local_time(events_queryset)
        .annotate(weekday=ExtractWeekDay('local_ts', tzinfo=UTC), hour=ExtractHour('local_ts', tzinfo=UTC))
        .values('weekday', 'hour')
        .annotate(count=Count('id'))
        .order_by()
    )
    for row in buckets:
        # ExtractWeekDay is 1=Sunday … 7=Saturday; the grid is Monday-first.
        grid[(row['weekday'] + 5) % 7][row['hour']] += row['count']

    max_count = max(max(row) for row in grid)
    rows = []
    for weekday, counts in enumerate(grid):
        cells = []
        for hour, count in enumerate(counts):
            style, dark = _heat_style(count, max_count)
            cells.append({'hour': hour, 'count': count, 'style': style, 'dark': dark})
        rows.append({'label': WEEKDAY_LABELS[weekday], 'cells': cells, 'total': sum(counts)})

    hour_totals = [sum(grid[d][h] for d in range(7)) for h in range(24)]
    busiest = None
    if max_count:
        busiest_day, busiest_hour = max(
            ((d, h) for d in range(7) for h in range(24)), key=lambda dh: grid[dh[0]][dh[1]],
        )
        busiest = {'day': WEEKDAY_LABELS[busiest_day], 'hour': busiest_hour, 'count': max_count}
    return {
        'rows': rows,
        'hours': list(range(24)),
        'hour_totals': hour_totals,
        'max_count': max_count,
        'busiest': busiest,
    }


def _columns_for_window(days: int) -> list[dict]:
    """Heatmap/trend columns: one per day up to 30 days, one per 7-day
    week beyond that (a 90-column grid doesn't fit the dashboard).
    """
    today = timezone.localdate()
    first_day = today - datetime.timedelta(days=days - 1)
    step = 1 if days <= 30 else 7
    columns = []
    start = first_day
    while start <= today:
        end = min(start + datetime.timedelta(days=step - 1), today)
        label = start.strftime('%b %-d') if step == 1 else f"{start.strftime('%b %-d')}–{end.strftime('%-d')}"
        columns.append({'start': start, 'end': end, 'label': label})
        start = end + datetime.timedelta(days=1)
    return columns


def _column_index(columns: list[dict], day: datetime.date) -> int | None:
    for i, col in enumerate(columns):
        if col['start'] <= day <= col['end']:
            return i
    return None


def keyword_time_heatmap(keywords: list[Keyword], days: int) -> dict:
    """Clicks per keyword per day (or week, for 90 days) — which topics are
    heating up or cooling off. Rows are the given keywords, in order.
    """
    columns = _columns_for_window(days)
    counts = {kw.pk: [0] * len(columns) for kw in keywords}
    buckets = (
        _with_local_time(KeywordEvent.objects.filter(
            keyword__in=keywords, event_type=KeywordEvent.EventType.CLICK,
            occurred_at__gte=window_start_for(days),
        ))
        .annotate(day=TruncDate('local_ts', tzinfo=UTC))
        .values('keyword_id', 'day')
        .annotate(count=Count('id'))
        .order_by()
    )
    for row in buckets:
        index = _column_index(columns, row['day'])
        if index is not None:
            counts[row['keyword_id']][index] += row['count']

    max_count = max([c for row in counts.values() for c in row] + [0])
    rows = []
    for kw in keywords:
        cells = []
        for col, count in zip(columns, counts[kw.pk]):
            style, dark = _heat_style(count, max_count)
            cells.append({'label': col['label'], 'count': count, 'style': style, 'dark': dark})
        rows.append({'keyword': kw, 'cells': cells, 'total': sum(counts[kw.pk])})
    return {'columns': columns, 'rows': rows, 'max_count': max_count}


def daily_trend(events_queryset, days: int) -> list[dict]:
    """Impressions/clicks per column (day, or week for 90 days), with bar
    heights as a % of the busiest column's impressions — same shape as
    ads/views.py:_bucket_ad_events_by_day's output for the same bar chart.
    """
    columns = _columns_for_window(days)
    buckets = [{'label': col['label'], 'impressions': 0, 'clicks': 0} for col in columns]
    daily = (
        _with_local_time(events_queryset.filter(occurred_at__gte=window_start_for(days)))
        .annotate(day=TruncDate('local_ts', tzinfo=UTC))
        .values('event_type', 'day')
        .annotate(count=Count('id'))
        .order_by()
    )
    for row in daily:
        index = _column_index(columns, row['day'])
        if index is None:
            continue
        key = 'impressions' if row['event_type'] == KeywordEvent.EventType.IMPRESSION else 'clicks'
        buckets[index][key] += row['count']

    max_value = max([b['impressions'] for b in buckets] + [b['clicks'] for b in buckets] + [1])
    for b in buckets:
        b['impressions_pct'] = round(b['impressions'] / max_value * 100)
        b['clicks_pct'] = round(b['clicks'] / max_value * 100)
        b['ctr'] = ctr(b['clicks'], b['impressions'])
    return buckets
