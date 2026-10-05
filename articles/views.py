import datetime
import json
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Case, Count, F, FloatField, IntegerField, Q, Value, When, prefetch_related_objects
from django.db.models.expressions import RawSQL
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import strip_tags
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit

from ajna_health_lens.comments_views import pop_comment_flash
from ajna_health_lens.mail import send_templated_email
from billing.access import (
    FREE_SAMPLE_LIMIT_PER_MONTH, GIFTABLE_ACCESS_TYPES, METERED_ACCESS_TYPES, article_is_accessible,
    consume_free_sample, create_or_get_article_gift, free_sample_reads_used, get_existing_article_gift,
    get_valid_article_gift, gift_articles_remaining,
)
from editorial_board.models import EditorialBoardMember
from issues.models import Issue
from newsletter.models import Subscriber
from sections.models import SectionFollow
from training.models import TrainingCourse
from users.decorators import role_required
from users.models import User

from . import bylines as byline_utils
from .citations import linkify_citations
from .content_ads import build_content_blocks
from .content_templates import ARTICLE_TYPE_CONTENT_TEMPLATES
from .toc import MIN_HEADINGS_FOR_TOC, extract_toc
from .forms import (
    ArticleCorrectionForm, ArticleForm, ArticleNoteForm, DraftArticleForm, LenientArticleForm,
    PublishArticleForm, ScheduleArticleForm, edit_token_for,
)
from .models import (
    HOME_SECTIONS_CACHE_KEY, Article, ArticleCorrection, ArticleNote, ArticleRevision, ArticleView, Author, Bookmark,
    Keyword, KeywordEvent, KeywordFollow,
)
from .revisions import compare, record_revision, restore_revision

# A keyword used on this many articles or fewer has nothing meaningful to
# "follow" yet — a keyword used exactly once is structurally guaranteed to
# never surface a second article. Only gates whether the Follow *button*
# shows (keyword_follow_toggle, ArticleListView below) — an existing follow
# on a keyword that later drops back to/below this count is left alone
# (see KeywordFollow's own docstring), so this constant is deliberately not
# consulted by ForYouView or send_topic_digests.
KEYWORD_FOLLOW_MIN_ARTICLES = 1
from .seo import breadcrumb_list_structured_data, news_article_structured_data, person_structured_data
from .similarity import similar_articles

# Article types treated as "peer-reviewed research" for the homepage's
# "From the Journal" section — everything except news/editorial/letters.
RESEARCH_TYPES = [
    Article.ArticleType.ORIGINAL_RESEARCH, Article.ArticleType.REVIEW_ARTICLE,
    Article.ArticleType.CASE_REPORT, Article.ArticleType.METHODOLOGY_PAPER,
    Article.ArticleType.SHORT_COMMUNICATION,
]
OPINION_TYPES = [Article.ArticleType.EDITORIAL, Article.ArticleType.LETTER_TO_EDITOR]

# Article CRUD (manage/ views below) is an editorial capability — ARCHITECTURE.md
# §6.3 grants "Access admin: Yes" to Editor/EiC/Admin only. Single source of
# truth is User.EDITORIAL_ROLES (see users/models.py) — not redefined here.
EDITORIAL_ROLES = User.EDITORIAL_ROLES


VIEW_DEDUP_WINDOW_MINUTES = 30


def _record_article_view(request, article) -> bool:
    """Powers the homepage's Trending section (HomeView._build_sections) —
    skips editorial staff (so QA/editing an article doesn't inflate its own
    numbers) and de-duplicates repeat views from the same session within a
    short window (a page refresh isn't a new "view"). Falls back to always
    recording if no session key is available, rather than risking
    conflating two different sessionless visitors under the same empty key.

    Returns whether a view was actually counted — ArticleDetailView uses it
    to count keyword impressions under exactly the same rules.
    """
    if request.user.is_authenticated and request.user.is_editorial_staff:
        return False
    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key
    if not session_key:
        ArticleView.objects.create(article=article)
        return True
    cutoff = timezone.now() - datetime.timedelta(minutes=VIEW_DEDUP_WINDOW_MINUTES)
    recent_duplicate = ArticleView.objects.filter(
        article=article, session_key=session_key, viewed_at__gte=cutoff,
    ).exists()
    if recent_duplicate:
        return False
    ArticleView.objects.create(article=article, session_key=session_key)
    return True


def _record_keyword_impressions(request, article, keywords) -> None:
    """One KeywordEvent impression per keyword shown on a counted article
    view — the denominator of the Keyword Analytics page's click-through
    rate. Only called when _record_article_view counted the view, so staff
    and refreshes are excluded from impressions the same way they are from
    clicks (keyword_click below).
    """
    if not keywords:
        return
    session_key = request.session.session_key or ''
    KeywordEvent.objects.bulk_create([
        KeywordEvent(
            keyword=keyword, article=article, event_type=KeywordEvent.EventType.IMPRESSION,
            session_key=session_key,
        )
        for keyword in keywords
    ])


@require_POST
@ratelimit(key='ip', rate='60/m', method='POST', block=True)
def keyword_click(request, pk):
    """Records a keyword-pill click, sent by navigator.sendBeacon from
    article_detail.html as the reader follows the pill's normal link — a
    beacon rather than a tracked redirect so the pill's href stays the real
    /articles/?keyword=<slug> URL (crawlers keep following it as ordinary
    internal linking, and bots that don't run JS don't inflate clicks).
    Always 204: the browser ignores a beacon's response, and a skipped
    (staff/duplicate) click isn't an error.
    """
    keyword = get_object_or_404(Keyword, pk=pk)
    if request.user.is_authenticated and request.user.is_editorial_staff:
        return HttpResponse(status=204)

    article = None
    article_id = request.POST.get('article')
    if article_id and article_id.isdigit():
        article = Article.objects.filter(pk=int(article_id)).first()
    placement = request.POST.get('placement', '')
    if placement not in KeywordEvent.Placement.values:
        placement = ''

    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key or ''
    if session_key:
        cutoff = timezone.now() - datetime.timedelta(minutes=VIEW_DEDUP_WINDOW_MINUTES)
        if KeywordEvent.objects.filter(
            keyword=keyword, article=article, session_key=session_key,
            event_type=KeywordEvent.EventType.CLICK, occurred_at__gte=cutoff,
        ).exists():
            return HttpResponse(status=204)

    KeywordEvent.objects.create(
        keyword=keyword, article=article, event_type=KeywordEvent.EventType.CLICK,
        placement=placement, session_key=session_key,
    )
    return HttpResponse(status=204)


RELATED_ARTICLES_LIMIT = 3


def related_articles_for(article, limit: int = RELATED_ARTICLES_LIMIT) -> list:
    """"Related reading" for an article page: the editor's hand-picked
    Article.related_articles when there are any (published ones only,
    newest first), otherwise the most text-similar published articles
    (articles/similarity.py — TF-IDF cosine similarity over title,
    keywords, abstract and body). Returns fewer than `limit`, or none,
    rather than padding with articles that aren't actually related.
    """
    curated = list(
        article.related_articles.filter(status=Article.Status.PUBLISHED)
        .exclude(pk=article.pk).order_by('-published_at', '-created_at')[:limit],
    )
    if curated:
        return curated
    return [related for related, _score in similar_articles(article, limit=limit)]


def _trending_articles(limit=5):
    """Published articles ranked by page views in the last 7 days (not an
    all-time count), so this reflects what's hot *now*, not what was hot
    once. Shared by HomeView's Trending section and ArticleDetailView's
    sidebar — see ArticleView in models.py for where these rows get
    recorded (and _record_article_view above for the dedup rules).
    """
    trending_cutoff = timezone.now() - datetime.timedelta(days=7)
    trending_counts = (
        ArticleView.objects.filter(viewed_at__gte=trending_cutoff, article__status=Article.Status.PUBLISHED)
        .values('article').annotate(view_count=Count('id')).order_by('-view_count')[:limit]
    )
    view_counts_by_pk = {row['article']: row['view_count'] for row in trending_counts}
    articles = list(
        Article.objects.filter(pk__in=view_counts_by_pk).prefetch_related('articleauthor_set__author__user'),
    )
    articles.sort(key=lambda article: -view_counts_by_pk[article.pk])
    for article in articles:
        article.week_view_count = view_counts_by_pk[article.pk]
    return articles


class HomeView(TemplateView):
    """Journal homepage: hero story, latest news, opinion, research
    highlights, special issues, and an editorial board preview.

    Each section is editor-curated first: Article.homepage_section lets an
    editor explicitly place a specific article in the Hero / Latest News /
    Opinion & Editorial / Research Highlights slot, regardless of its
    article_type (see /manage/articles/, Publishing tab). Any slots an
    editor hasn't explicitly filled auto-fill from recent published articles
    of the matching type — the previous, fully-automatic behavior — so a
    section is never empty just because nothing's been curated yet. An
    article picked for one section (explicit or auto-filled) never repeats
    in a later one.
    """

    template_name = 'home.html'

    # Short TTL — cheap insurance against a publish/unpublish looking stale
    # for more than a few minutes, while still saving the ~8 queries below
    # on every anonymous homepage hit. Bumped whenever the section-building
    # logic changes shape, so a deploy doesn't unpickle a stale-shaped dict.
    CACHE_KEY = HOME_SECTIONS_CACHE_KEY
    CACHE_TTL = 300

    def _build_sections(self):
        """Every homepage section — identical for every visitor (no
        per-user data), so this whole dict is cache-safe and cached as one
        unit. get_context_data adds the one visitor-specific bit
        (already_subscribed_to_newsletter) after reading this from cache.
        """
        # -created_at as a tiebreaker: articles that share a publication_date
        # (or have none) still sort newest-first instead of by arbitrary DB order.
        published = Article.objects.filter(status=Article.Status.PUBLISHED).order_by(
            '-is_pinned', '-published_at', '-created_at',
        )
        used_pks = set()

        def pick(section, limit, type_filter=None):
            picks = list(published.filter(homepage_section=section).exclude(pk__in=used_pks)[:limit])
            used_pks.update(a.pk for a in picks)
            if len(picks) < limit:
                # Autofill only draws from articles with no explicit
                # homepage_section — one earmarked for a *different* section
                # (not yet processed or not chosen for it) must never get
                # swept up as filler here instead, even by Hero's fallback,
                # which has no type_filter and would otherwise happily grab
                # anything recent.
                remaining = published.filter(homepage_section='').exclude(pk__in=used_pks)
                if type_filter is not None:
                    remaining = remaining.filter(type_filter)
                autofill = list(remaining[:limit - len(picks)])
                picks += autofill
                used_pks.update(a.pk for a in autofill)
            return picks

        HomepageSection = Article.HomepageSection
        sections = {}

        hero_picks = pick(HomepageSection.HERO, 1)
        hero_article = hero_picks[0] if hero_picks else None
        sections['hero_article'] = hero_article
        sections['hero_authors'] = (
            list(hero_article.articleauthor_set.select_related('author__user').order_by('order')) if hero_article else []
        )

        latest_news = pick(HomepageSection.LATEST_NEWS, 3, Q(article_type=Article.ArticleType.NEWS_COMMENTARY))
        opinion_pieces = pick(HomepageSection.OPINION, 3, Q(article_type__in=OPINION_TYPES))
        research_highlights = pick(HomepageSection.RESEARCH, 2, Q(article_type__in=RESEARCH_TYPES))
        # Any story with a YouTube link, not just type "Video" — a news story
        # with a clip belongs in the video row too.
        videos = pick(HomepageSection.VIDEOS, 8, ~Q(video_url=''))

        # Sections are built as plain lists (picks + autofill concatenated),
        # not querysets, so prefetching happens post-hoc via
        # prefetch_related_objects instead of queryset.prefetch_related().
        prefetch_related_objects(latest_news, 'articleauthor_set__author__user')
        prefetch_related_objects(opinion_pieces, 'articleauthor_set__author__user')
        prefetch_related_objects(research_highlights, 'articleauthor_set__author__user', 'issue')

        sections['latest_news'] = latest_news
        sections['opinion_pieces'] = opinion_pieces
        sections['research_highlights'] = research_highlights
        prefetch_related_objects(videos, 'section')
        sections['home_videos'] = videos

        sections['special_issues'] = list(Issue.objects.all()[:3])
        sections['board_preview'] = list(EditorialBoardMember.objects.filter(is_active=True)[:6])

        # Trending — the one section that's purely algorithm-driven, not
        # editor-curated (no HomepageSection value for it) and not subject
        # to the used_pks dedup above; it's fine for a trending piece to
        # also appear in a curated section.
        sections['trending_articles'] = _trending_articles(limit=5)
        return sections

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sections = cache.get(self.CACHE_KEY)
        if sections is None:
            sections = self._build_sections()
            cache.set(self.CACHE_KEY, sections, self.CACHE_TTL)
        context.update(sections)

        # Hides the homepage newsletter CTA (templates/home.html) for a
        # logged-in reader who's already confirmed — no point nagging them.
        # Always shown to anonymous visitors, who might not have an account.
        # Deliberately computed fresh every request, outside the cached
        # dict above — this is the one piece of the homepage that varies
        # by visitor and must never be cached.
        if self.request.user.is_authenticated:
            context['already_subscribed_to_newsletter'] = Subscriber.objects.filter(
                user=self.request.user, status=Subscriber.Status.CONFIRMED,
            ).exists()

        # Training row — outside the cached dict above, since HOME_SECTIONS_CACHE_KEY
        # is only invalidated by Article.save(), not by course edits.
        context['home_courses'] = list(
            TrainingCourse.objects.filter(is_active=True).annotate(
                active_enrollment_count=Count('enrollments', filter=~Q(enrollments__status='cancelled')),
            ).order_by('-is_featured', 'start_date', 'title')[:3],
        )

        context['meta_description'] = f'{settings.JOURNAL_TAGLINE} — health news, research highlights, and commentary from {settings.JOURNAL_NAME}.'
        return context


class VideoListView(ListView):
    """/videos/ — every published story with a YouTube video (the "Videos"
    menu entry), newest first; the newest is shown large at the top."""

    template_name = 'articles/video_list.html'
    context_object_name = 'videos'
    paginate_by = 13

    def get_queryset(self):
        return (
            Article.objects.filter(status=Article.Status.PUBLISHED).exclude(video_url='')
            .select_related('section').prefetch_related('articleauthor_set__author__user')
            .order_by('-is_pinned', '-published_at', '-created_at')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meta_description'] = f'Health videos from {settings.JOURNAL_NAME}: explainers, interviews and reports.'
        return context


class ArticleListView(ListView):
    """All published articles, paginated by 10, optionally filtered by
    ?type=<article_type> (this also serves as the "News" section — pass
    type=news_commentary — per ROADMAP.md Phase 3 rather than a separate view)
    and/or ?keyword=<slug> — an exact match against Keyword.slug via the
    Article.keyword_tags M2M (August 2026: was an icontains substring match
    against a flat comma-separated CharField; see Keyword's docstring in
    articles/models.py for why that changed).
    """

    model = Article
    template_name = 'articles/article_list.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        queryset = Article.objects.filter(status=Article.Status.PUBLISHED).order_by(
            '-is_pinned', '-published_at', '-created_at',
        ).prefetch_related('articleauthor_set__author__user')
        article_type = self.request.GET.get('type')
        if article_type:
            queryset = queryset.filter(article_type=article_type)
        keyword = self.request.GET.get('keyword')
        if keyword:
            queryset = queryset.filter(keyword_tags__slug=keyword)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['article_types'] = Article.ArticleType.choices
        context['selected_type'] = self.request.GET.get('type', '')
        selected_keyword_slug = self.request.GET.get('keyword', '')
        context['selected_keyword'] = selected_keyword_slug
        selected_keyword_label = (
            Keyword.objects.filter(slug=selected_keyword_slug).values_list('name', flat=True).first() or ''
            if selected_keyword_slug else ''
        )
        context['selected_keyword_label'] = selected_keyword_label
        context['keyword_follow_eligible'] = False
        context['is_following_keyword'] = False
        if selected_keyword_slug:
            keyword = Keyword.objects.filter(slug=selected_keyword_slug).annotate(
                article_count=Count('articles'),
            ).first()
            if keyword and keyword.article_count > KEYWORD_FOLLOW_MIN_ARTICLES:
                context['keyword_follow_eligible'] = True
                context['is_following_keyword'] = (
                    self.request.user.is_authenticated
                    and KeywordFollow.objects.filter(user=self.request.user, keyword=keyword).exists()
                )
        # Pre-fills the Tagify keyword-search box (article_list.html) in its
        # expected format — same {"value", "slug"} shape keyword_autocomplete
        # returns, so the same JS "add" handler that reads .data.slug works
        # whether the tag came from a fresh autocomplete pick or this initial
        # server-rendered state.
        context['selected_keyword_json'] = (
            json.dumps([{'value': selected_keyword_label, 'slug': selected_keyword_slug}])
            if selected_keyword_label else '[]'
        )
        if selected_keyword_label:
            context['meta_title'] = f'Articles tagged "{selected_keyword_label}" — {settings.JOURNAL_NAME}'
            context['meta_description'] = f'Articles about {selected_keyword_label} from {settings.JOURNAL_NAME}.'
        elif context['selected_type']:
            type_label = dict(Article.ArticleType.choices).get(context['selected_type'], '')
            context['meta_title'] = f'{type_label} — {settings.JOURNAL_NAME}'
            context['meta_description'] = f'{type_label} articles from {settings.JOURNAL_NAME}.'
        else:
            context['meta_title'] = f'All Articles — {settings.JOURNAL_NAME}'
            context['meta_description'] = f'Browse all published articles from {settings.JOURNAL_NAME}.'
        return context


class ArchiveListView(ListView):
    """Public browsing of archived articles (ROADMAP.md Phase 10 Session 7)
    — titles/abstracts always visible, matching this app's existing
    "abstract always public" convention for every other gated tier; full
    text stays gated on the detail page (billing.access.article_is_accessible's
    ARCHIVED branch), not hidden from this list. No login required just to
    browse what exists, same as the main article list.
    """

    model = Article
    template_name = 'articles/archive_list.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        return Article.objects.filter(
            status=Article.Status.ARCHIVED,
        ).order_by('-published_at', '-created_at').prefetch_related('articleauthor_set__author__user')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meta_title'] = f'Archive — {settings.JOURNAL_NAME}'
        context['meta_description'] = f'Archived articles from {settings.JOURNAL_NAME}.'
        return context


@method_decorator(login_required, name='dispatch')
class ForYouView(ListView):
    """A reader's personalized feed — published articles from every Section
    or Keyword they follow (see sections.models.SectionFollow,
    articles.models.KeywordFollow, ROADMAP.md Phase 10 Sessions 3 & 5),
    combined into one de-duplicated feed (an article matching both a
    followed section and a followed keyword appears once, not twice), most
    recent first. login_required rather than hiding the nav link for an
    anonymous visitor — there's no feed to build without an account to key
    follows off of, so the page itself explains that instead of 404ing or
    silently redirecting.
    """

    model = Article
    template_name = 'articles/for_you.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        followed_section_ids = SectionFollow.objects.filter(
            user=self.request.user,
        ).values_list('section_id', flat=True)
        followed_keyword_ids = KeywordFollow.objects.filter(
            user=self.request.user,
        ).values_list('keyword_id', flat=True)
        return Article.objects.filter(
            Q(section_id__in=followed_section_ids) | Q(keyword_tags__in=followed_keyword_ids),
            status=Article.Status.PUBLISHED,
        ).distinct().order_by(
            '-is_pinned', '-published_at', '-created_at',
        ).prefetch_related('articleauthor_set__author__user')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['has_follows'] = (
            SectionFollow.objects.filter(user=self.request.user).exists()
            or KeywordFollow.objects.filter(user=self.request.user).exists()
        )
        context['meta_title'] = f'For You — {settings.JOURNAL_NAME}'
        context['meta_robots'] = 'noindex, follow'  # personalized, not a page worth indexing
        return context


class ArticleDetailView(DetailView):
    """Abstract and metadata are always public. Full-text body (html_content)
    is gated by the real paywall — billing.access.article_is_accessible — which
    checks access_type against the viewer's active subscription/purchase, not
    just the tier the article is set to.
    """

    model = Article
    template_name = 'articles/article_detail.html'
    context_object_name = 'article'

    def get_queryset(self):
        # ARCHIVED is included so an archived article stays reachable at
        # its own permalink — full-text access is still gated (see
        # article_is_accessible's grants_full_archive check), just not a
        # blanket 404 the way it was before Session 7.
        return Article.objects.filter(status__in=[Article.Status.PUBLISHED, Article.Status.ARCHIVED])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        view_counted = _record_article_view(self.request, self.object)

        article_authors = list(self.object.articleauthor_set.select_related('author__user').order_by('order'))
        context['article_authors'] = article_authors
        context['featured_author'] = next(
            (aa for aa in article_authors if aa.is_corresponding), article_authors[0] if article_authors else None,
        )
        show_full_text = article_is_accessible(self.request.user, self.object)
        context['free_sample_notice'] = None
        context['gift_banner'] = None
        # /articles/<slug>/gift/<gift_token>/ (articles:article_gift_view)
        # routes to this same view with an extra URL kwarg, rather than a
        # separate view duplicating all the context-building below — an
        # expired/unknown token isn't an error, it just falls through to
        # the normal access rules (real entitlement, then metering) as if
        # no gift link were involved.
        gift_token = self.kwargs.get('gift_token')
        gift = get_valid_article_gift(self.object, gift_token) if gift_token else None
        if gift:
            show_full_text = True
            context['gift_banner'] = gift.gifter
        elif not show_full_text and self.object.access_type in METERED_ACCESS_TYPES:
            # Metering is a separate, stateful concern from the real
            # entitlement check above — see billing.access.consume_free_sample's
            # own docstring for why the two aren't merged into one function.
            if consume_free_sample(self.request, self.object):
                show_full_text = True
                context['free_sample_notice'] = {
                    'used': free_sample_reads_used(self.request),
                    'limit': FREE_SAMPLE_LIMIT_PER_MONTH,
                }
        context['show_full_text'] = show_full_text
        context['is_bookmarked'] = (
            self.request.user.is_authenticated
            and Bookmark.objects.filter(user=self.request.user, article=self.object).exists()
        )
        context['gift_link'] = None
        context['gift_remaining'] = None
        # Only offered to a *real* subscriber (show_full_text via a genuine
        # entitlement, not a free sample) — a reader who only got in on the
        # metered allowance has nothing of their own to give away.
        if (
            self.object.access_type in GIFTABLE_ACCESS_TYPES
            and self.request.user.is_authenticated
            and article_is_accessible(self.request.user, self.object)
        ):
            existing_gift = get_existing_article_gift(self.request.user, self.object)
            remaining = gift_articles_remaining(self.request.user)
            if existing_gift or remaining > 0:
                context['gift_remaining'] = remaining
                if existing_gift:
                    context['gift_link'] = self.request.build_absolute_uri(
                        reverse('articles:article_gift_view', args=[self.object.slug, existing_gift.token]),
                    )
        # One-shot "comment posted / check your email / now live" notice
        # from ajna_health_lens/comments_views.py, shown in the comments section.
        context['comment_flash'] = pop_comment_flash(self.request, self.request.path)
        context['keyword_list'] = list(self.object.keyword_tags.all())
        context['corrections'] = list(self.object.corrections.all())
        if view_counted:
            _record_keyword_impressions(self.request, self.object, context['keyword_list'])
        html_with_ids, toc_entries = extract_toc(linkify_citations(self.object.html_content))
        context['toc_entries'] = toc_entries if len(toc_entries) > MIN_HEADINGS_FOR_TOC else []
        context['content_blocks'] = build_content_blocks(html_with_ids)
        if self.object.references:
            context['references_list'] = [
                line.strip() for line in self.object.references.strip().splitlines() if line.strip()
            ]
        context['related_articles'] = related_articles_for(self.object)
        prefetch_related_objects(context['related_articles'], 'articleauthor_set__author__user')

        # Fetch one extra and trim, so excluding the article being viewed
        # (it'd be a strange thing to see "trending" on its own page) still
        # leaves a full 5 whenever it would otherwise have placed in the top 5.
        context['trending_articles'] = [
            a for a in _trending_articles(limit=6) if a.pk != self.object.pk
        ][:5]

        # Social-share preview (Open Graph/Twitter Card, templates/base.html)
        # and search-engine structured data — the article page is the one
        # place on the site actually shared/linked out, so it's the one that
        # gets real per-page metadata rather than the sitewide default.
        # Search & social overrides (editor's "Search & social" card) win when set.
        context['meta_title'] = self.object.seo_title or self.object.title
        context['meta_description'] = self.object.seo_description or self.object.summary[:200]
        context['og_type'] = 'article'
        context['canonical_url'] = self.request.build_absolute_uri(self.request.path)
        context['short_url'] = self.request.build_absolute_uri(
            reverse('articles:article_short_link', kwargs={'code': self.object.short_code}),
        )
        # card_image_url: the featured image, else a video story's YouTube
        # thumbnail (already absolute), so a video shares with a picture too.
        image_url = self.request.build_absolute_uri(self.object.card_image_url) if self.object.card_image_url else None
        share_image = self.object.social_image.url if self.object.social_image else self.object.card_image_url
        context['meta_image_url'] = self.request.build_absolute_uri(share_image) if share_image else None
        context['structured_data_json'] = news_article_structured_data(
            self.object, journal_name=settings.JOURNAL_NAME, canonical_url=context['canonical_url'],
            image_url=image_url, publisher_logo_url=self.request.build_absolute_uri(static('images/logo.png')),
            authors=article_authors, keywords=context['keyword_list'], corrections=context['corrections'],
        )
        context['breadcrumb_json'] = breadcrumb_list_structured_data([
            ('Home', self.request.build_absolute_uri(reverse('articles:home'))),
            ('Articles', self.request.build_absolute_uri(reverse('articles:article_list'))),
            (self.object.title, None),
        ])
        return context


def article_short_link(request, code):
    """/articles/<code>/ — a short, shareable alternative to the full
    title-slug URL (e.g. /articles/3f2a4/ instead of
    /articles/tuberculosis-screening-update-3f2a4/). Redirects (301) to the
    canonical slug URL rather than rendering the page directly at this path,
    so there's exactly one indexable URL per article — the usual reason
    short-link services redirect instead of serving duplicate content.

    `code` is only guaranteed to *look like* a short_code (the URL converter
    enforces the shape, not uniqueness against real slugs) — an editor can
    still manually type a real slug that happens to be the same shape (e.g.
    "abcde"). Falls through to rendering the detail page directly for that
    case instead of 404ing; redirecting to the same URL string it's already
    on would loop.
    """
    article = Article.objects.filter(short_code=code, status=Article.Status.PUBLISHED).first()
    if article:
        return redirect('articles:article_detail', slug=article.slug, permanent=True)
    return ArticleDetailView.as_view()(request, slug=code)


class AuthorDetailView(DetailView):
    """Public byline page for an Author profile (/authors/<slug>/) — with or
    without a site account. Only active authors with at least one published
    byline, or whose linked account has an active editorial-board listing,
    have a page; anyone else 404s, so an author profile an editor is still
    setting up is never public by accident.
    """

    model = Author
    template_name = 'articles/author_detail.html'
    context_object_name = 'author'

    def get_queryset(self):
        return Author.objects.filter(is_active=True).filter(
            Q(articles__status=Article.Status.PUBLISHED) | Q(user__board_memberships__is_active=True),
        ).select_related('user').distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        author = self.object
        context['author_articles'] = author.articles.filter(
            status=Article.Status.PUBLISHED,
        ).order_by('-published_at', '-created_at').prefetch_related('articleauthor_set__author__user')
        context['board_membership'] = (
            author.user.board_memberships.filter(is_active=True).first() if author.user_id else None
        )
        context['meta_title'] = f'{author.name} — {settings.JOURNAL_NAME}'
        byline = author.name
        if author.display_affiliation:
            byline += f', {author.display_affiliation}'
        context['meta_description'] = author.display_bio[:200] or f'{byline} — articles on {settings.JOURNAL_NAME}.'
        photo = author.display_photo
        image_url = self.request.build_absolute_uri(photo.url) if photo else None
        if image_url:
            context['meta_image_url'] = image_url
        context['structured_data_json'] = person_structured_data(author, image_url=image_url)
        return context


def legacy_author_redirect(request, pk):
    """/authors/<int>/ was keyed by *user* id before author pages moved to
    Author profiles (/authors/<slug>/). Old links and bookmarks still land:
    the account's author profile, permanently redirected, or a 404.
    """
    author = get_object_or_404(Author, user_id=pk, is_active=True)
    return redirect(author, permanent=True)


CITATION_FORMATS = ('bibtex', 'ris', 'text')


def article_citation(request, slug, citation_format):
    if citation_format not in CITATION_FORMATS:
        raise Http404

    article = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED)
    authors = [aa.display_name for aa in article.articleauthor_set.select_related('author__user').order_by('order')]
    year = article.publication_date.year if article.publication_date else ''

    if citation_format == 'bibtex':
        content = (
            f'@article{{{article.slug},\n'
            f'  title = {{{article.title}}},\n'
            f'  author = {{{" and ".join(authors)}}},\n'
            f'  year = {{{year}}},\n'
            f'  journal = {{Ajna Health Lens}},\n'
            f'  doi = {{{article.doi or ""}}}\n'
            f'}}\n'
        )
        content_type = 'application/x-bibtex'
    elif citation_format == 'ris':
        lines = ['TY  - JOUR', f'TI  - {article.title}']
        lines += [f'AU  - {a}' for a in authors]
        lines += [f'PY  - {year}', 'JO  - Ajna Health Lens', f'DO  - {article.doi or ""}', 'ER  - ']
        content = '\n'.join(lines) + '\n'
        content_type = 'application/x-research-info-systems'
    else:
        content = f'{", ".join(authors)} ({year}). {article.title}. Ajna Health Lens.\n'
        content_type = 'text/plain'

    # citation_count was a migrated-but-never-incremented field (August 2026
    # gap audit) — an F() update avoids a read-modify-write race between
    # concurrent citation requests for the same article.
    Article.objects.filter(pk=article.pk).update(citation_count=F('citation_count') + 1)

    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{article.slug}.{citation_format}"'
    return response


def article_download(request, slug):
    """Counts a PDF download, then redirects to the real file — the PDF
    itself is served directly (by Django in dev, nginx in production per
    ARCHITECTURE.md §9.2), so this small indirection is the only hook point
    for download_count (previously migrated but never incremented — August
    2026 gap audit). Same paywall gate as the article page itself.
    """
    article = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED)
    if not article.pdf_file or not pdf_is_accessible(request, article):
        raise Http404
    Article.objects.filter(pk=article.pk).update(download_count=F('download_count') + 1)
    # pdf_file.url is /protected-media/..., which runs the same check again
    # (ajna_health_lens/media_views.py) — so the URL is useless if shared.
    return redirect(article.pdf_file.url)


def pdf_is_accessible(request, article) -> bool:
    """Who may fetch an article's PDF: editorial staff (any status, to
    check it), otherwise only for a published article the reader can read.
    Same combined check as ArticleDetailView — a reader who got in via a
    consumed free sample may download it too. Re-consuming is a no-op:
    consume_free_sample treats a re-read of the same article within the
    same period as free, not a second charge."""
    user = request.user
    if user.is_authenticated and user.role in EDITORIAL_ROLES:
        return True
    if article.status != Article.Status.PUBLISHED:
        return False
    return article_is_accessible(user, article) or (
        article.access_type in METERED_ACCESS_TYPES and consume_free_sample(request, article)
    )


@login_required
@require_POST
def article_bookmark_toggle(request, slug):
    """Save/unsave, in one endpoint — same shape as
    sections:section_follow_toggle (the template only needs the current
    state to decide which label to show). Deliberately not paywall-gated —
    an abstract-only, subscription-required article can still be saved for
    later; a reader shouldn't have to pass the paywall just to bookmark
    something they intend to subscribe and come back to.
    """
    article = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED)
    bookmark, created = Bookmark.objects.get_or_create(user=request.user, article=article)
    if not created:
        bookmark.delete()
        messages.success(request, _('Removed from your reading list.'))
    else:
        messages.success(request, _('Saved to your reading list.'))
    return redirect('articles:article_detail', slug=article.slug)


@login_required
@require_POST
def article_gift_create(request, slug):
    """Creates (or finds this period's existing) shareable gift link for a
    subscription-tier article — quota-gated by billing.access.
    create_or_get_article_gift, which also enforces that only a real
    subscriber with an active plan/allowance reaches this at all. Redirects
    back to the article page, where the link is now shown (ArticleDetailView's
    gift_link context) — no separate "your gift link" page.
    """
    article = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED)
    gift = create_or_get_article_gift(request.user, article)
    if gift is None:
        messages.error(request, _("You don't have a gift available for this article right now."))
    else:
        messages.success(request, _('Your gift link is ready — copy it below to share.'))
    return redirect('articles:article_detail', slug=article.slug)


@method_decorator(login_required, name='dispatch')
class ReadingListView(ListView):
    """A reader's saved articles (Bookmark, see above), most recently saved
    first. login_required rather than hiding the nav link — there's no list
    to build without an account to key bookmarks off of.
    """

    model = Article
    template_name = 'articles/reading_list.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        bookmarked_article_ids = Bookmark.objects.filter(
            user=self.request.user,
        ).order_by('-bookmarked_at').values_list('article_id', flat=True)
        # Bookmark.Meta.ordering (-bookmarked_at) is lost once articles are
        # pulled through a separate Article queryset — Case/When preserves
        # the original save order instead of falling back to Article's own
        # default ordering (-is_pinned, -publication_date, ...), which would
        # otherwise silently reorder a reader's own reading list out from
        # under them every time a newly-pinned article jumped to the top.
        preserved_order = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(bookmarked_article_ids)])
        return Article.objects.filter(
            pk__in=bookmarked_article_ids, status=Article.Status.PUBLISHED,
        ).order_by(preserved_order).prefetch_related('articleauthor_set__author__user')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meta_title'] = f'Reading List — {settings.JOURNAL_NAME}'
        context['meta_robots'] = 'noindex, follow'  # personal, not a page worth indexing
        return context


# Chars MySQL's BOOLEAN MODE gives special meaning to (+ - < > ( ) ~ * " @) —
# stripped from each token before it's wrapped as a required prefix match,
# so a reader typing e.g. "COVID-19" doesn't accidentally write boolean syntax.
_BOOLEAN_MODE_SPECIAL_CHARS = re.compile(r'[+\-<>()~*"@]')


def _fulltext_boolean_query(raw_query):
    """Turns free-text input into a MySQL BOOLEAN MODE AGAINST() expression:
    every word becomes a required (+), prefix (*) match, so word order and
    which indexed column it landed in don't matter, and partial words still
    match (e.g. "tubercul" finds "tuberculosis"). Tokens under 3 characters
    are dropped — MySQL's own minimum indexed token length (innodb_ft_min_token_size,
    default 3) would never match them anyway, and a bare "+" is a BOOLEAN MODE
    syntax error. Returns '' if nothing usable is left (e.g. a query that's
    only short acronyms), signaling the caller to skip full-text matching
    and rely on the icontains fallback instead.
    """
    tokens = []
    for word in raw_query.split():
        cleaned = _BOOLEAN_MODE_SPECIAL_CHARS.sub('', word)
        if len(cleaned) >= 3:
            tokens.append(f'+{cleaned}*')
    return ' '.join(tokens)


@method_decorator(ratelimit(key='ip', rate='30/m', method='GET', block=True), name='dispatch')
class SearchView(ListView):
    """Public search — backed by a MySQL FULLTEXT index on (title, abstract)
    (see migration 0015, narrowed in 0021 when keywords moved off this table
    onto Keyword/keyword_tags — see articles/models.py) for real word-based
    matching, e.g. word order doesn't matter and results aren't limited to a
    single contiguous substring. The plain icontains scan is kept alongside
    it (not replaced) for three reasons: author name and keyword name aren't
    part of the FULLTEXT index, and short tokens (under MySQL's ~3-char
    minimum, common for medical acronyms like "TB"/"HIV"/"flu") would
    otherwise silently stop matching anything.
    """

    model = Article
    template_name = 'articles/search_results.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.query = self.request.GET.get('q', '').strip()
        # ARCHIVED included — "full searchability... of historical
        # articles" (Session 7) is specifically what makes archival access
        # worth gating as a perk; excluding archived content from search
        # would make grants_full_archive largely undiscoverable.
        queryset = Article.objects.filter(
            status__in=[Article.Status.PUBLISHED, Article.Status.ARCHIVED],
        ).prefetch_related('articleauthor_set__author__user')
        if self.query:
            boolean_query = _fulltext_boolean_query(self.query)
            icontains_filter = (
                Q(title__icontains=self.query)
                | Q(abstract__icontains=self.query)
                | Q(keyword_tags__name__icontains=self.query)
                | Q(authors__name__icontains=self.query)
            )
            if boolean_query:
                relevance = RawSQL(
                    'MATCH(articles_article.title, articles_article.abstract) '
                    'AGAINST (%s IN BOOLEAN MODE)',
                    (boolean_query,), output_field=FloatField(),
                )
                queryset = queryset.annotate(relevance=relevance).filter(
                    icontains_filter | Q(relevance__gt=0),
                )
            else:
                queryset = queryset.annotate(
                    relevance=Value(0.0, output_field=FloatField()),
                ).filter(icontains_filter)
            # A title match still ranks first regardless of full-text score —
            # deterministic and keeps the most obviously-relevant result on
            # top rather than trusting MySQL's opaque relevance number for
            # the primary sort.
            queryset = queryset.distinct().annotate(
                title_match=Case(When(title__icontains=self.query, then=0), default=1, output_field=IntegerField()),
            ).order_by('title_match', '-relevance', '-published_at', '-created_at')
        else:
            queryset = queryset.order_by('-published_at', '-created_at')
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.query
        context['meta_title'] = (
            f'Search results for "{self.query}" — {settings.JOURNAL_NAME}' if self.query
            else f'Search — {settings.JOURNAL_NAME}'
        )
        context['meta_description'] = f'Search {settings.JOURNAL_NAME} for articles by title, abstract, author, or keyword.'
        # Internal search-result pages are thin/near-duplicate content that
        # shouldn't compete with the real article/list pages they surface —
        # standard practice (Google's own crawling docs recommend it), not
        # specific to this being a health-news site.
        context['meta_robots'] = 'noindex, follow'
        return context


@ratelimit(key='ip', rate='30/m', method='GET', block=True)
def keyword_autocomplete(request):
    """Suggests existing Keyword names for a Tagify input to autocomplete
    from — shared by the editorial article form (ArticleForm's keywords
    field) and the public keyword search box (templates/articles/article_list.html).
    Public/unauthenticated on purpose: a reader typing into the public
    keyword search needs the same suggestions an editor gets, and the
    response is read-only (existing keyword names only, never creates one —
    that only happens on an actual article save, see TagifyKeywordsField).
    """
    query = request.GET.get('q', '').strip()
    keywords = Keyword.objects.filter(name__icontains=query)[:20] if query else Keyword.objects.all()[:20]
    return JsonResponse([{'value': kw.name, 'slug': kw.slug} for kw in keywords], safe=False)


RELATED_SUGGESTION_LIMIT = 8


@role_required(*EDITORIAL_ROLES)
def related_article_autocomplete(request):
    """Tagify suggestions for the article form's "Related articles" picker —
    published articles whose title matches `q`, excluding the article being
    edited (`exclude`). Editorial-only, unlike keyword_autocomplete: it's
    only ever used from the editorial form.
    """
    query = request.GET.get('q', '').strip()
    articles = Article.objects.filter(status=Article.Status.PUBLISHED)
    if query:
        articles = articles.filter(title__icontains=query)
    exclude = request.GET.get('exclude', '')
    if exclude.isdigit():
        articles = articles.exclude(pk=int(exclude))
    articles = articles.order_by('-published_at', '-created_at')[:20]
    return JsonResponse(
        [{'value': a.title, 'id': a.pk, 'type': a.get_article_type_display()} for a in articles], safe=False,
    )


@role_required(*EDITORIAL_ROLES)
def related_article_suggestions(request):
    """Most text-similar published articles for the article form's
    "Related" tab (see articles/similarity.py), with the cosine similarity
    as a 0–100 score. Works on drafts: the article's saved text (autosave
    keeps it current) is compared against the published corpus.
    """
    article_id = request.GET.get('article', '')
    if not article_id.isdigit():
        return JsonResponse({'suggestions': [], 'reason': 'unsaved'})
    article = get_object_or_404(Article, pk=int(article_id))
    suggestions = similar_articles(article, limit=RELATED_SUGGESTION_LIMIT)
    return JsonResponse({'suggestions': [
        {
            'id': related.pk, 'value': related.title, 'type': related.get_article_type_display(),
            'score': round(score * 100, 1),
            'url': reverse('articles:article_detail', args=[related.slug]),
        }
        for related, score in suggestions
    ]})


@login_required
@require_POST
def keyword_follow_toggle(request, slug):
    """Follow/unfollow, in one endpoint — same shape as
    sections:section_follow_toggle and articles:article_bookmark_toggle.

    The KEYWORD_FOLLOW_MIN_ARTICLES eligibility check only gates *creating*
    a new follow — removing an existing one always works regardless of the
    keyword's current usage count. Otherwise a keyword that later drops
    back to/below the threshold (e.g. an article unpublished or retagged)
    would leave an existing follower with no way to unfollow it from here,
    contradicting KeywordFollow's own docstring, which promises exactly
    that an existing follow is left alone by a usage change.
    """
    keyword = get_object_or_404(Keyword, slug=slug)
    existing = KeywordFollow.objects.filter(user=request.user, keyword=keyword).first()
    if existing:
        existing.delete()
        messages.success(request, _('Unfollowed "%(name)s".') % {'name': keyword.name})
    else:
        if keyword.articles.count() <= KEYWORD_FOLLOW_MIN_ARTICLES:
            raise Http404
        KeywordFollow.objects.create(user=request.user, keyword=keyword)
        messages.success(request, _('Following "%(name)s" — new articles will appear in your feed and weekly digest.') % {'name': keyword.name})
    return redirect(f"{reverse('articles:article_list')}?keyword={keyword.slug}")


# -- Editorial article management (CRUD, not public browsing) --------------

@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ArticleManageListView(ListView):
    """All articles regardless of status, for editorial management —
    distinct from ArticleListView above, which only shows published ones.
    """

    model = Article
    template_name = 'articles/manage/article_list.html'
    context_object_name = 'articles'
    paginate_by = 20

    def get_queryset(self):
        queryset = Article.objects.select_related('issue', 'assigned_to').order_by('-updated_at')
        status = self.request.GET.get('status')
        article_type = self.request.GET.get('type')
        homepage_section = self.request.GET.get('homepage_section')
        q = self.request.GET.get('q')
        if status:
            queryset = queryset.filter(status=status)
        if self.request.GET.get('assigned') == 'me':
            queryset = queryset.filter(assigned_to=self.request.user)
        if article_type:
            queryset = queryset.filter(article_type=article_type)
        if homepage_section:
            queryset = queryset.filter(homepage_section=homepage_section)
        if q:
            queryset = queryset.filter(title__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['article_types'] = Article.ArticleType.choices
        context['statuses'] = Article.Status.choices
        # A scheduled article still waiting 3+ minutes past its time means the
        # every-minute publish job isn't running (qcluster down) — flagged in the list.
        context['overdue_before'] = timezone.now() - datetime.timedelta(minutes=3)
        context['homepage_sections'] = Article.HomepageSection.choices
        context['selected_type'] = self.request.GET.get('type', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_assigned'] = self.request.GET.get('assigned', '')
        context['selected_homepage_section'] = self.request.GET.get('homepage_section', '')
        context['selected_q'] = self.request.GET.get('q', '')
        return context


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_quick_publish(request, slug):
    """One-click publish/unpublish from the manage list — a concrete action
    for "how do I actually publish this", instead of only a status dropdown
    buried in the edit form's Publishing tab. Publishing stamps
    publication_date via Article.save(), same as saving the full edit form.
    """
    article = get_object_or_404(Article, slug=slug)
    if not request.user.can_publish:
        messages.error(request, NOT_A_PUBLISHER)
        return redirect('articles:manage_article_list')
    if article.status == Article.Status.PUBLISHED:
        article.status = Article.Status.DRAFT
        messages.success(request, f'"{article.title}" moved back to draft.')
    else:
        # Same rule as the editor's Publish button (PublishArticleForm):
        # nothing goes live without something to read.
        if not strip_tags(article.html_content or '').strip() and not article.pdf_file:
            messages.error(request, f'"{article.title}" has no article text yet — open it and add the text before publishing.')
            return redirect('articles:manage_article_list')
        # A Scheduled article published from here goes live now — save()
        # pulls its future published_at back to the current time.
        article.status = Article.Status.PUBLISHED
        messages.success(request, f'"{article.title}" published.')
    article.save()
    record_revision(
        article, request.user,
        ArticleRevision.Action.PUBLISHED if article.status == Article.Status.PUBLISHED else ArticleRevision.Action.UNPUBLISHED,
    )
    return redirect('articles:manage_article_list')


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_correction_add(request, slug):
    """Appends a correction/clarification/update note to an article and
    stamps its last_updated_at — readers see "Updated" plus the note."""
    article = get_object_or_404(Article, slug=slug)
    if article.status == Article.Status.PUBLISHED and not request.user.can_publish:
        raise PermissionDenied
    form = ArticleCorrectionForm(request.POST)
    if form.is_valid():
        correction = form.save(commit=False)
        correction.article = article
        correction.created_by = request.user
        correction.save()
        if article.status == Article.Status.PUBLISHED:
            Article.objects.filter(pk=article.pk).update(last_updated_at=correction.created_at)
        messages.success(request, f'{correction.get_kind_display()} added — it now shows on the article.')
    else:
        messages.error(request, 'Write the note before adding it.')
    return redirect(f"{reverse('articles:manage_article_update', args=[article.slug])}#corrections")


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_correction_delete(request, pk):
    """Removes a note added by mistake (e.g. a typo in the note itself)."""
    correction = get_object_or_404(ArticleCorrection, pk=pk)
    if correction.article.status == Article.Status.PUBLISHED and not request.user.can_publish:
        raise PermissionDenied
    slug = correction.article.slug
    correction.delete()
    messages.success(request, 'Note removed.')
    return redirect(f"{reverse('articles:manage_article_update', args=[slug])}#corrections")


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_note_add(request, slug):
    """Internal editorial note — for the team, never shown to readers."""
    article = get_object_or_404(Article, slug=slug)
    form = ArticleNoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.article = article
        note.author = request.user
        note.save()
        messages.success(request, 'Note added.')
    else:
        messages.error(request, 'Write the note before adding it.')
    return redirect(f"{reverse('articles:manage_article_update', args=[article.slug])}#notes")


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_note_delete(request, pk):
    """Notes can be removed by whoever wrote them, or by senior staff."""
    note = get_object_or_404(ArticleNote, pk=pk)
    if note.author_id != request.user.pk and not request.user.is_senior_staff:
        raise PermissionDenied
    slug = note.article.slug
    note.delete()
    messages.success(request, 'Note removed.')
    return redirect(f"{reverse('articles:manage_article_update', args=[slug])}#notes")


@role_required(*EDITORIAL_ROLES)
def article_history(request, slug):
    """Revision history: every save, who made it and what they did, with a
    word-level comparison against the previous version (?compare=<pk>)."""
    article = get_object_or_404(Article, slug=slug)
    revisions = list(article.revisions.select_related('user'))
    selected = None
    changes = []
    compare_pk = request.GET.get('compare')
    if compare_pk:
        selected = next((r for r in revisions if str(r.pk) == compare_pk), None)
        if selected is None:
            raise Http404
    elif revisions:
        selected = revisions[0]
    if selected:
        index = revisions.index(selected)
        previous = revisions[index + 1] if index + 1 < len(revisions) else None
        changes = compare(previous, selected)
    return render(request, 'articles/manage/article_history.html', {
        'article': article, 'revisions': revisions, 'selected': selected, 'changes': changes,
    })


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_revision_restore(request, pk):
    """Puts an earlier version's words back. On a live article this changes
    what readers see immediately (the button says so)."""
    revision = get_object_or_404(ArticleRevision, pk=pk)
    if revision.article.status in LIVE_OR_QUEUED and not request.user.can_publish:
        raise PermissionDenied
    article = restore_revision(revision, request.user)
    messages.success(request, f'Restored the version from {_format_local(revision.created_at)}.')
    return redirect('articles:manage_article_update', slug=article.slug)


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_autosave(request):
    """Background autosave from the article editor (every ~20s while a draft
    has unsaved changes) — saves whatever's been filled in so far, using
    LenientArticleForm (nothing but a title needed). For a brand-new article this defaults status to
    Draft; for an article that already exists, status is left exactly as it
    was — autosaving edits to an already-published article must not
    silently unpublish it. Never *sets* Published — that only ever happens
    via the explicit Save & Publish button.
    """
    pk = request.POST.get('article_pk')
    instance = get_object_or_404(Article, pk=pk) if pk else None
    # Autosave only ever touches drafts: writing half-typed edits straight
    # into a live article would publish them. Published/archived articles
    # change only through the explicit Update button.
    if instance is not None and instance.status in LIVE_OR_QUEUED:
        return JsonResponse({'ok': False, 'errors': {'__all__': ['Autosave is off for published articles.']}}, status=409)
    # Same overwrite protection as a real save: a stale tab must not
    # silently replace someone else's newer changes in the background.
    token = request.POST.get('edit_token')
    if instance is not None and token and token != edit_token_for(instance):
        return JsonResponse({'ok': False, 'conflict': True, 'errors': {'__all__': [
            'Someone else saved this article after you opened it — autosave is paused. Reload to see their changes.',
        ]}}, status=409)
    if not request.POST.get('title', '').strip():
        return JsonResponse({'ok': False, 'errors': {'title': ['Add a title to start saving.']}}, status=400)

    form = LenientArticleForm(request.POST, request.FILES, instance=instance)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)

    article = form.save(commit=False)
    if instance is None:
        article.status = Article.Status.DRAFT
    # A blank slug is auto-generated (from the title + a unique short_code)
    # by Article.save() itself now — no need to pre-fill it here.

    try:
        article.save()
        form.save_m2m()  # keyword_tags — see ArticleForm.save()'s commit=False contract
    except IntegrityError:
        return JsonResponse(
            {'ok': False, 'errors': {'__all__': ['Could not save — check the slug and DOI are unique.']}}, status=400,
        )

    record_revision(article, request.user, ArticleRevision.Action.AUTOSAVED)
    return JsonResponse({
        'ok': True, 'article_pk': article.pk, 'slug': article.slug, 'edit_token': edit_token_for(article),
        'created_authors': form.created_authors,
        'edit_url': reverse('articles:manage_article_update', kwargs={'slug': article.slug}),
    })


def _format_local(value) -> str:
    """"Sep 29, 2026 at 6:00 AM" in the site's time zone, for messages."""
    return date_format(timezone.localtime(value), 'M j, Y \\a\\t g:i A')


# action (the button's name="action" value) → (form class, new status).
# None keeps the current status. See ArticleFormMixin.
ARTICLE_ACTIONS = {
    'draft': ('DraftArticleForm', Article.Status.DRAFT),        # Save draft / Back to draft / Unpublish
    'save': ('DraftArticleForm', None),                         # Save (in review / ready — stays there)
    'review': ('DraftArticleForm', Article.Status.IN_REVIEW),   # Send for review
    'ready': ('PublishArticleForm', Article.Status.READY),      # Mark ready — must be publishable
    'schedule': ('ScheduleArticleForm', Article.Status.SCHEDULED),
    'publish': ('PublishArticleForm', Article.Status.PUBLISHED),  # Publish / Update live article
    'keep': ('PublishArticleForm', None),                       # Save an archived article
}
LIVE_OR_QUEUED = (Article.Status.PUBLISHED, Article.Status.SCHEDULED, Article.Status.ARCHIVED)
NOT_A_PUBLISHER = (
    'Only publishers can publish, schedule or change a live article. Send it for review or mark it ready — '
    'a publisher will take it from there.'
)


def _requires_publisher(action, previous) -> bool:
    """Actions that put something in front of readers (or take it away)."""
    if action in ('publish', 'schedule', 'keep'):
        return True
    return action == 'draft' and previous is not None and previous.status in LIVE_OR_QUEUED


def _revision_action(previous_status, action):
    """Which history entry a save produces, e.g. "publish" on an already
    live article is an Update, on anything else a first Publish."""
    Action = ArticleRevision.Action
    if action == 'publish':
        return Action.UPDATED if previous_status == Article.Status.PUBLISHED else Action.PUBLISHED
    if action == 'draft' and previous_status in LIVE_OR_QUEUED:
        return Action.UNPUBLISHED
    return {
        'review': Action.SUBMITTED, 'ready': Action.APPROVED, 'schedule': Action.SCHEDULED,
    }.get(action, Action.SAVED if previous_status else Action.CREATED)


class ArticleFormMixin:
    """Shared by create/update. The buttons (name="action") decide both the
    new status and how strictly the form is checked — there's no status
    dropdown that could disagree with the button the editor clicked (see
    ARTICLE_ACTIONS): a draft or a story in review needs only a title;
    "Mark ready", Publish and Schedule need everything a reader will see.

    Every save also records a revision (articles/revisions.py) and, when a
    story is assigned to or sent for review to another editor, emails them.
    Saves are refused if someone else saved the article since this editor
    opened it (the hidden edit_token), instead of silently overwriting.
    """

    def _action(self):
        action = self.request.POST.get('action')
        previous = getattr(self, '_previous', None)
        # "Save" never relaxes the checks on something live or queued.
        if action == 'save' and previous and previous.status in LIVE_OR_QUEUED:
            return 'keep'
        return action if action in ARTICLE_ACTIONS else None

    def get_form_class(self):
        action = self._action()
        if not action:
            return ArticleForm
        return {'DraftArticleForm': DraftArticleForm, 'PublishArticleForm': PublishArticleForm,
                'ScheduleArticleForm': ScheduleArticleForm}[ARTICLE_ACTIONS[action][0]]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['content_templates'] = {str(k): v for k, v in ARTICLE_TYPE_CONTENT_TEMPLATES.items()}
        my_author = Author.objects.filter(user=self.request.user, is_active=True).first()
        context['my_author_json'] = json.dumps(byline_utils.author_payload(my_author)) if my_author else ''
        context['author_search_url'] = reverse('articles:manage_author_search')
        context['correction_form'] = ArticleCorrectionForm()
        return context

    def get_success_url(self):
        return reverse('articles:manage_article_update', kwargs={'slug': self.object.slug})

    def form_valid(self, form):
        action = self._action()
        previous = getattr(self, '_previous', None)
        previous_status = previous.status if previous else None

        if _requires_publisher(action, previous) and not self.request.user.can_publish:
            form.add_error(None, NOT_A_PUBLISHER)
            return self.form_invalid(form)

        if previous is not None:
            token = form.cleaned_data.get('edit_token')
            if token and token != edit_token_for(previous):
                latest = previous.revisions.select_related('user').first()
                who = (latest.user.get_full_name() or latest.user.email) if latest and latest.user else 'Someone'
                when = _format_local(previous.updated_at)
                form.add_error(None, (
                    f'{who} saved changes to this article at {when}, after you opened it. '
                    'Your changes were NOT saved, to avoid overwriting theirs. Copy anything you need, then reload the page.'
                ))
                return self.form_invalid(form)

        new_status = ARTICLE_ACTIONS[action][1] if action else None
        if new_status:
            form.instance.status = new_status
        if action == 'publish' and previous_status == Article.Status.PUBLISHED:
            form.instance.last_updated_at = timezone.now()
        if action == 'schedule':
            form.instance.published_at = form.cleaned_data['schedule_at']
        breaking = form.cleaned_data.get('breaking_hours') if self.request.user.can_publish else ''
        if breaking == 'off':
            form.instance.breaking_until = None
        elif breaking:
            form.instance.breaking_until = timezone.now() + datetime.timedelta(hours=int(breaking))

        response = super().form_valid(form)
        record_revision(self.object, self.request.user, _revision_action(previous_status, action))
        self._notify_assignee(previous, action)
        if action == 'ready':
            self._notify_publishers_ready()
        messages.success(self.request, f'"{self.object.title}" {self._message(previous_status, action, form)}.')
        return response

    def _message(self, previous_status, action, form):
        was_live = previous_status == Article.Status.PUBLISHED
        if action == 'publish':
            return 'updated — the live article now shows your changes' if was_live else 'published'
        if action == 'schedule':
            return f'scheduled for {_format_local(form.cleaned_data["schedule_at"])}'
        if action == 'review':
            assignee = self.object.assigned_to
            return f'sent for review{f" to {assignee.get_full_name() or assignee.email}" if assignee else ""}'
        if action == 'ready':
            return 'marked ready to publish'
        if action == 'draft':
            if was_live:
                return 'unpublished and moved back to draft'
            if previous_status == Article.Status.SCHEDULED:
                return 'unscheduled and moved back to draft'
            if previous_status in (Article.Status.IN_REVIEW, Article.Status.READY):
                return 'moved back to draft'
            return 'saved as a draft' if previous_status is None else 'draft saved'
        return 'saved'

    def _notify_assignee(self, previous, action):
        """Email the assigned editor when a story is newly assigned to them
        or sent to them for review — never for their own actions."""
        assignee = self.object.assigned_to
        if not assignee or assignee == self.request.user or not assignee.email:
            return
        newly_assigned = previous is None or previous.assigned_to_id != assignee.pk
        if not (newly_assigned or action == 'review'):
            return
        send_templated_email(
            subject=f'{"Review requested" if action == "review" else "Assigned to you"}: {self.object.title}',
            template='articles/email/assigned',
            context={
                'article': self.object, 'assignee': assignee, 'by': self.request.user,
                'for_review': action == 'review',
                'edit_url': f"{settings.SITE_BASE_URL}{reverse('articles:manage_article_update', args=[self.object.slug])}",
            },
            recipient_list=[assignee.email],
        )

    def _notify_publishers_ready(self):
        """A story marked ready is waiting on a publisher — tell them (except
        whoever marked it, who can publish it themselves if they're one)."""
        publishers = [
            user for user in User.objects.filter(is_active=True, role__in=User.EDITORIAL_ROLES).exclude(pk=self.request.user.pk)
            if user.can_publish and user.email
        ]
        if not publishers:
            return
        send_templated_email(
            subject=f'Ready to publish: {self.object.title}',
            template='articles/email/ready_to_publish',
            context={
                'article': self.object, 'by': self.request.user,
                'edit_url': f"{settings.SITE_BASE_URL}{reverse('articles:manage_article_update', args=[self.object.slug])}",
            },
            recipient_list=[user.email for user in publishers],
        )

    def form_invalid(self, form):
        action = self._action()
        if not form.non_field_errors():
            if action in ('draft', 'save', 'review'):
                messages.error(self.request, 'Not saved — a title is required.')
            else:
                messages.error(self.request, 'Not saved yet — fix the highlighted fields below.')
        return super().form_invalid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ArticleCreateView(ArticleFormMixin, CreateView):
    model = Article
    form_class = ArticleForm
    template_name = 'articles/manage/article_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ArticleUpdateView(ArticleFormMixin, UpdateView):
    model = Article
    form_class = ArticleForm
    template_name = 'articles/manage/article_form.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def post(self, request, *args, **kwargs):
        # The article as saved before this request — for the status the
        # buttons move it from, the conflict check, and assignee changes.
        self._previous = self.get_object()
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        # The slug as saved — the form's instance may hold a half-edited or
        # blank one when the form is shown again with errors.
        context['saved_slug'] = (getattr(self, '_previous', None) or self.object).slug
        context['note_form'] = ArticleNoteForm()
        context['notes'] = self.object.notes.select_related('author')
        context['revision_count'] = self.object.revisions.count()
        return context


@role_required(*EDITORIAL_ROLES)
def article_manage_authors(request, slug):
    """Old separate byline page — authors are now edited in the article
    form's own Authors box (articles/bylines.py). Kept as a redirect so old
    links and bookmarks still land somewhere useful."""
    article = get_object_or_404(Article, slug=slug)
    return redirect(f"{reverse('articles:manage_article_update', args=[article.slug])}#authors")


@role_required(*EDITORIAL_ROLES)
def author_search(request):
    """Authors box lookup: active author profiles matching ?q=."""
    return JsonResponse({'results': byline_utils.search(request.GET.get('q', ''))})


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ArticleDeleteView(DeleteView):
    model = Article
    template_name = 'articles/manage/article_confirm_delete.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    success_url = reverse_lazy('articles:manage_article_list')

    def dispatch(self, request, *args, **kwargs):
        # Deleting a live or queued article takes it off the site — a publishing decision.
        article = self.get_object()
        if article.status in LIVE_OR_QUEUED and request.user.is_authenticated and not request.user.can_publish:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object.title}" deleted.')
        return super().form_valid(form)


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_preview(request):
    """Render in-progress form data through the real article_detail.html
    template — without saving anything — so an editor sees exactly what the
    published page will look like, D3 charts and all.
    """
    # When previewing an edit, bind the form to its existing instance — otherwise
    # the slug/DOI uniqueness validators reject the article's own current values
    # as duplicates of themselves.
    source_pk = request.POST.get('preview_source_pk')
    source = Article.objects.filter(pk=source_pk).first() if source_pk else None

    form = ArticleForm(request.POST, request.FILES, instance=source)
    if not form.is_valid():
        return render(request, 'articles/manage/article_preview_error.html', {'form': form}, status=400)

    article = form.save(commit=False)

    # The Authors box's current (unsaved) list; nothing is created for a
    # preview. Without it in the POST, fall back to the saved bylines.
    article_authors = []
    if form.cleaned_data.get('bylines') is not None:
        article_authors = byline_utils.preview_bylines(form.cleaned_data['bylines'])
    elif source:
        article_authors = list(source.articleauthor_set.select_related('author__user').order_by('order'))

    context = {
        'article': article,
        'article_authors': article_authors,
        'featured_author': next(
            (aa for aa in article_authors if aa.is_corresponding), article_authors[0] if article_authors else None,
        ),
        # Previewing is already gated to editorial staff (role_required above),
        # so the preview always shows full text regardless of access_type.
        'show_full_text': True,
        'preview_mode': True,
        # Same rule as the live page (related_articles_for) — editor picks
        # first, else text similarity — but from the form's unsaved picks,
        # text and keywords, so the preview matches what saving would show.
        'related_articles': (
            [a for a in form.cleaned_data.get('related_articles', []) if a.pk != article.pk][:RELATED_ARTICLES_LIMIT]
            or [
                related for related, _score in similar_articles(
                    article, limit=RELATED_ARTICLES_LIMIT,
                    keyword_names=[kw.name for kw in form.cleaned_data.get('keywords', [])],
                )
            ]
        ),
        # article.keyword_tags can't be queried — this instance is never
        # saved (see the view's docstring), so it has no pk. Pulled straight
        # from cleaned_data instead of the unsaved instance's M2M.
        'keyword_list': form.cleaned_data.get('keywords', []),
    }
    _html_with_ids, _toc_entries = extract_toc(linkify_citations(article.html_content))
    context['toc_entries'] = _toc_entries if len(_toc_entries) > MIN_HEADINGS_FOR_TOC else []
    context['content_blocks'] = build_content_blocks(_html_with_ids)
    if article.references:
        context['references_list'] = [
            line.strip() for line in article.references.strip().splitlines() if line.strip()
        ]
    return render(request, 'articles/article_detail.html', context)
