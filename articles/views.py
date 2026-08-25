import datetime
import re

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Case, Count, F, FloatField, IntegerField, Q, Value, When, prefetch_related_objects
from django.db.models.expressions import RawSQL
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView
from django_ratelimit.decorators import ratelimit

from billing.access import article_is_accessible
from editorial_board.models import EditorialBoardMember
from issues.models import Issue
from newsletter.models import Subscriber
from users.decorators import role_required
from users.models import User

from .citations import linkify_citations
from .content_ads import build_content_blocks
from .content_templates import ARTICLE_TYPE_CONTENT_TEMPLATES
from .toc import MIN_HEADINGS_FOR_TOC, extract_toc
from .forms import ArticleAuthorFormSet, ArticleForm, LenientArticleForm
from .models import HOME_SECTIONS_CACHE_KEY, Article, ArticleView
from .seo import news_article_structured_data

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


def _record_article_view(request, article):
    """Powers the homepage's Trending section (HomeView._build_sections) —
    skips editorial staff (so QA/editing an article doesn't inflate its own
    numbers) and de-duplicates repeat views from the same session within a
    short window (a page refresh isn't a new "view"). Falls back to always
    recording if no session key is available, rather than risking
    conflating two different sessionless visitors under the same empty key.
    """
    if request.user.is_authenticated and request.user.is_editorial_staff:
        return
    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key
    if not session_key:
        ArticleView.objects.create(article=article)
        return
    cutoff = timezone.now() - datetime.timedelta(minutes=VIEW_DEDUP_WINDOW_MINUTES)
    recent_duplicate = ArticleView.objects.filter(
        article=article, session_key=session_key, viewed_at__gte=cutoff,
    ).exists()
    if not recent_duplicate:
        ArticleView.objects.create(article=article, session_key=session_key)


class ComingSoonView(TemplateView):
    """Pre-launch placeholder at "/" — see the routing note in articles/urls.py."""

    template_name = 'coming_soon.html'


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
        Article.objects.filter(pk__in=view_counts_by_pk).prefetch_related('articleauthor_set__user'),
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
            '-is_pinned', '-publication_date', '-created_at',
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
            list(hero_article.articleauthor_set.select_related('user').order_by('order')) if hero_article else []
        )

        latest_news = pick(HomepageSection.LATEST_NEWS, 3, Q(article_type=Article.ArticleType.NEWS_COMMENTARY))
        opinion_pieces = pick(HomepageSection.OPINION, 3, Q(article_type__in=OPINION_TYPES))
        research_highlights = pick(HomepageSection.RESEARCH, 2, Q(article_type__in=RESEARCH_TYPES))

        # Sections are built as plain lists (picks + autofill concatenated),
        # not querysets, so prefetching happens post-hoc via
        # prefetch_related_objects instead of queryset.prefetch_related().
        prefetch_related_objects(latest_news, 'articleauthor_set__user')
        prefetch_related_objects(opinion_pieces, 'articleauthor_set__user')
        prefetch_related_objects(research_highlights, 'articleauthor_set__user', 'issue')

        sections['latest_news'] = latest_news
        sections['opinion_pieces'] = opinion_pieces
        sections['research_highlights'] = research_highlights

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

        return context


class ArticleListView(ListView):
    """All published articles, paginated by 10, optionally filtered by
    ?type=<article_type> (this also serves as the "News" section — pass
    type=news_commentary — per ROADMAP.md Phase 3 rather than a separate view)
    and/or ?keyword=<value> (Article.keywords is a flat comma-separated
    CharField, not a real tag model — see the split_comma template filter —
    so this is an icontains match against it, not an exact-tag lookup).
    """

    model = Article
    template_name = 'articles/article_list.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        queryset = Article.objects.filter(status=Article.Status.PUBLISHED).order_by(
            '-is_pinned', '-publication_date', '-created_at',
        ).prefetch_related('articleauthor_set__user')
        article_type = self.request.GET.get('type')
        if article_type:
            queryset = queryset.filter(article_type=article_type)
        keyword = self.request.GET.get('keyword')
        if keyword:
            queryset = queryset.filter(keywords__icontains=keyword)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['article_types'] = Article.ArticleType.choices
        context['selected_type'] = self.request.GET.get('type', '')
        context['selected_keyword'] = self.request.GET.get('keyword', '')
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
        return Article.objects.filter(status=Article.Status.PUBLISHED)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        _record_article_view(self.request, self.object)

        article_authors = list(self.object.articleauthor_set.select_related('user').order_by('order'))
        context['article_authors'] = article_authors
        context['featured_author'] = next(
            (aa for aa in article_authors if aa.is_corresponding), article_authors[0] if article_authors else None,
        )
        context['show_full_text'] = article_is_accessible(self.request.user, self.object)
        html_with_ids, toc_entries = extract_toc(linkify_citations(self.object.html_content))
        context['toc_entries'] = toc_entries if len(toc_entries) > MIN_HEADINGS_FOR_TOC else []
        context['content_blocks'] = build_content_blocks(html_with_ids)
        if self.object.references:
            context['references_list'] = [
                line.strip() for line in self.object.references.strip().splitlines() if line.strip()
            ]
        context['related_articles'] = Article.objects.filter(
            status=Article.Status.PUBLISHED, article_type=self.object.article_type,
        ).exclude(pk=self.object.pk).order_by('-publication_date', '-created_at')[:3]

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
        context['meta_title'] = self.object.title
        context['meta_description'] = (self.object.abstract or '')[:200]
        context['og_type'] = 'article'
        context['canonical_url'] = self.request.build_absolute_uri(self.request.path)
        context['short_url'] = self.request.build_absolute_uri(
            reverse('articles:article_short_link', kwargs={'code': self.object.short_code}),
        )
        image_url = None
        if self.object.featured_image:
            image_url = self.request.build_absolute_uri(self.object.featured_image.url)
        context['meta_image_url'] = image_url
        context['structured_data_json'] = news_article_structured_data(
            self.object, journal_name=settings.JOURNAL_NAME, canonical_url=context['canonical_url'],
            image_url=image_url, publisher_logo_url=self.request.build_absolute_uri(static('images/logo.png')),
            authors=article_authors,
        )
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
    """Public byline page for a contributor. Deliberately not a general user
    directory — the queryset only includes users with at least one published
    byline OR an active editorial board listing linked to their account, so
    unverified/no-byline accounts 404 here rather than exposing profile
    fields (bio, affiliation) never meant to be public. The board-membership
    branch matters for editors/EiC who are publicly featured on the board
    page but may not have authored any articles themselves — that link is
    only ever set by an editor (EDITORIAL_ROLES) editing the board member,
    so it's already a deliberate, trusted editorial decision.
    """

    model = User
    template_name = 'articles/author_detail.html'
    context_object_name = 'author'

    def get_queryset(self):
        return User.objects.filter(
            Q(authored_articles__status=Article.Status.PUBLISHED) | Q(board_memberships__is_active=True),
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['author_articles'] = self.object.authored_articles.filter(
            status=Article.Status.PUBLISHED,
        ).order_by('-publication_date', '-created_at')
        context['board_membership'] = self.object.board_memberships.filter(is_active=True).first()
        return context


CITATION_FORMATS = ('bibtex', 'ris', 'text')


def article_citation(request, slug, citation_format):
    if citation_format not in CITATION_FORMATS:
        raise Http404

    article = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED)
    authors = [aa.user.get_full_name() for aa in article.articleauthor_set.select_related('user').order_by('order')]
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
    if not article.pdf_file or not article_is_accessible(request.user, article):
        raise Http404
    Article.objects.filter(pk=article.pk).update(download_count=F('download_count') + 1)
    return redirect(article.pdf_file.url)


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
    """Public search — backed by a MySQL FULLTEXT index on (title, abstract,
    keywords) (see migration 0015) for real word-based matching, e.g. word
    order doesn't matter and results aren't limited to a single contiguous
    substring. The plain icontains scan is kept alongside it (not replaced)
    for two reasons: author name isn't part of the FULLTEXT index, and short
    tokens (under MySQL's ~3-char minimum, common for medical acronyms like
    "TB"/"HIV"/"flu") would otherwise silently stop matching anything.
    """

    model = Article
    template_name = 'articles/search_results.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.query = self.request.GET.get('q', '').strip()
        queryset = Article.objects.filter(
            status=Article.Status.PUBLISHED,
        ).prefetch_related('articleauthor_set__user')
        if self.query:
            boolean_query = _fulltext_boolean_query(self.query)
            icontains_filter = (
                Q(title__icontains=self.query)
                | Q(abstract__icontains=self.query)
                | Q(keywords__icontains=self.query)
                | Q(authors__first_name__icontains=self.query)
                | Q(authors__last_name__icontains=self.query)
            )
            if boolean_query:
                relevance = RawSQL(
                    'MATCH(articles_article.title, articles_article.abstract, articles_article.keywords) '
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
            ).order_by('title_match', '-relevance', '-publication_date', '-created_at')
        else:
            queryset = queryset.order_by('-publication_date', '-created_at')
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.query
        return context


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
        queryset = Article.objects.select_related('issue').order_by('-updated_at')
        status = self.request.GET.get('status')
        article_type = self.request.GET.get('type')
        homepage_section = self.request.GET.get('homepage_section')
        if status:
            queryset = queryset.filter(status=status)
        if article_type:
            queryset = queryset.filter(article_type=article_type)
        if homepage_section:
            queryset = queryset.filter(homepage_section=homepage_section)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['article_types'] = Article.ArticleType.choices
        context['statuses'] = Article.Status.choices
        context['homepage_sections'] = Article.HomepageSection.choices
        context['selected_type'] = self.request.GET.get('type', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_homepage_section'] = self.request.GET.get('homepage_section', '')
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
    if article.status == Article.Status.PUBLISHED:
        article.status = Article.Status.DRAFT
        messages.success(request, f'"{article.title}" moved back to draft.')
    else:
        article.status = Article.Status.PUBLISHED
        messages.success(request, f'"{article.title}" published.')
    article.save()
    return redirect('articles:manage_article_list')


@role_required(*EDITORIAL_ROLES)
@require_POST
def article_autosave(request):
    """Fires on each "Next"/"Back" tab click in the New/Edit Article wizard —
    saves whatever's been filled in so far, using LenientArticleForm
    (nothing required, so a half-finished Content tab doesn't block moving
    to Publishing/Media). For a brand-new article this defaults status to
    Draft; for an article that already exists, status is left exactly as it
    was — autosaving edits to an already-published article must not
    silently unpublish it. Never *sets* Published — that only ever happens
    via the explicit Save & Publish button.
    """
    pk = request.POST.get('article_pk')
    instance = get_object_or_404(Article, pk=pk) if pk else None

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
    except IntegrityError:
        return JsonResponse(
            {'ok': False, 'errors': {'__all__': ['Could not save — check the slug and DOI are unique.']}}, status=400,
        )

    return JsonResponse({
        'ok': True, 'article_pk': article.pk, 'slug': article.slug,
        'edit_url': reverse('articles:manage_article_update', kwargs={'slug': article.slug}),
    })


class ArticleFormMixin:
    """Shared context for create/update — the per-type content-template
    picker rendered in articles/manage/article_form.html — plus the
    Save as Draft / Save & Publish action handling. There's no manual
    status dropdown in this form on purpose: status is decided entirely by
    which of those two buttons was pressed (name="action", value="draft"
    or "publish"), so there's no separate control that could disagree with
    the button the editor actually clicked.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['content_templates'] = {str(k): v for k, v in ARTICLE_TYPE_CONTENT_TEMPLATES.items()}
        return context

    def get_success_url(self):
        return reverse('articles:manage_article_update', kwargs={'slug': self.object.slug})

    def form_valid(self, form):
        action = self.request.POST.get('action')
        if action == 'publish':
            form.instance.status = Article.Status.PUBLISHED
        elif action == 'draft':
            form.instance.status = Article.Status.DRAFT
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ArticleCreateView(ArticleFormMixin, CreateView):
    model = Article
    form_class = ArticleForm
    template_name = 'articles/manage/article_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        return context

    def form_valid(self, form):
        published = self.request.POST.get('action') == 'publish'
        messages.success(self.request, f'"{form.instance.title}" created{" and published" if published else " as a draft"}.')
        return super().form_valid(form)


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ArticleUpdateView(ArticleFormMixin, UpdateView):
    model = Article
    form_class = ArticleForm
    template_name = 'articles/manage/article_form.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = False
        return context

    def form_valid(self, form):
        action = self.request.POST.get('action')
        if action == 'publish':
            suffix = ' and published'
        elif action == 'draft':
            suffix = ' and moved back to draft'
        else:
            suffix = ''
        messages.success(self.request, f'"{form.instance.title}" updated{suffix}.')
        return super().form_valid(form)


@role_required(*EDITORIAL_ROLES)
def article_manage_authors(request, slug):
    """Byline editor — add/remove authors, set ordering and the
    corresponding-author flag. Replaces the Django admin's
    ArticleAuthorInline so this never has to be done in /admin/.
    """
    article = get_object_or_404(Article, slug=slug)
    if request.method == 'POST':
        formset = ArticleAuthorFormSet(request.POST, instance=article)
        if formset.is_valid():
            formset.save()
            messages.success(request, 'Authors updated.')
            return redirect('articles:manage_article_authors', slug=article.slug)
    else:
        formset = ArticleAuthorFormSet(instance=article)
    return render(request, 'articles/manage/article_authors.html', {'article': article, 'formset': formset})


@method_decorator(role_required(*EDITORIAL_ROLES), name='dispatch')
class ArticleDeleteView(DeleteView):
    model = Article
    template_name = 'articles/manage/article_confirm_delete.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    success_url = reverse_lazy('articles:manage_article_list')

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

    # Authors aren't editable from this form (see ArticleForm docstring) — for an
    # existing article, pull its real authors so the preview byline is accurate.
    article_authors = []
    if source:
        article_authors = list(source.articleauthor_set.select_related('user').order_by('order'))

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
        'related_articles': [],
    }
    _html_with_ids, _toc_entries = extract_toc(linkify_citations(article.html_content))
    context['toc_entries'] = _toc_entries if len(_toc_entries) > MIN_HEADINGS_FOR_TOC else []
    context['content_blocks'] = build_content_blocks(_html_with_ids)
    if article.references:
        context['references_list'] = [
            line.strip() for line in article.references.strip().splitlines() if line.strip()
        ]
    return render(request, 'articles/article_detail.html', context)
