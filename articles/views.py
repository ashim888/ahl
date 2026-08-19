from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Q, prefetch_related_objects
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from billing.access import article_is_accessible
from editorial_board.models import EditorialBoardMember
from issues.models import Issue
from users.decorators import role_required
from users.models import User

from .content_templates import ARTICLE_TYPE_CONTENT_TEMPLATES
from .forms import ArticleAuthorFormSet, ArticleForm, LenientArticleForm
from .models import Article

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


class ComingSoonView(TemplateView):
    """Pre-launch placeholder at "/" — see the routing note in articles/urls.py."""

    template_name = 'coming_soon.html'


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
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

        hero_picks = pick(HomepageSection.HERO, 1)
        hero_article = hero_picks[0] if hero_picks else None
        context['hero_article'] = hero_article
        if hero_article:
            context['hero_authors'] = hero_article.articleauthor_set.select_related('user').order_by('order')

        latest_news = pick(HomepageSection.LATEST_NEWS, 3, Q(article_type=Article.ArticleType.NEWS_COMMENTARY))
        opinion_pieces = pick(HomepageSection.OPINION, 3, Q(article_type__in=OPINION_TYPES))
        research_highlights = pick(HomepageSection.RESEARCH, 2, Q(article_type__in=RESEARCH_TYPES))

        # Sections are built as plain lists (picks + autofill concatenated),
        # not querysets, so prefetching happens post-hoc via
        # prefetch_related_objects instead of queryset.prefetch_related().
        prefetch_related_objects(latest_news, 'articleauthor_set__user')
        prefetch_related_objects(opinion_pieces, 'articleauthor_set__user')
        prefetch_related_objects(research_highlights, 'articleauthor_set__user', 'issue')

        context['latest_news'] = latest_news
        context['opinion_pieces'] = opinion_pieces
        context['research_highlights'] = research_highlights

        context['special_issues'] = Issue.objects.all()[:3]
        context['board_preview'] = EditorialBoardMember.objects.filter(is_active=True)[:6]
        return context


class ArticleListView(ListView):
    """All published articles, paginated by 10, optionally filtered by
    ?type=<article_type> (this also serves as the "News" section — pass
    type=news_commentary — per ROADMAP.md Phase 3 rather than a separate view).
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
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['article_types'] = Article.ArticleType.choices
        context['selected_type'] = self.request.GET.get('type', '')
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
        article_authors = list(self.object.articleauthor_set.select_related('user').order_by('order'))
        context['article_authors'] = article_authors
        context['featured_author'] = next(
            (aa for aa in article_authors if aa.is_corresponding), article_authors[0] if article_authors else None,
        )
        context['show_full_text'] = article_is_accessible(self.request.user, self.object)
        if self.object.references:
            context['references_list'] = [
                line.strip() for line in self.object.references.strip().splitlines() if line.strip()
            ]
        context['related_articles'] = Article.objects.filter(
            status=Article.Status.PUBLISHED, article_type=self.object.article_type,
        ).exclude(pk=self.object.pk).order_by('-publication_date', '-created_at')[:3]
        return context


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

    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{article.slug}.{citation_format}"'
    return response


class SearchView(ListView):
    model = Article
    template_name = 'articles/search_results.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        self.query = self.request.GET.get('q', '').strip()
        queryset = Article.objects.filter(
            status=Article.Status.PUBLISHED,
        ).order_by('-publication_date', '-created_at').prefetch_related('articleauthor_set__user')
        if self.query:
            queryset = queryset.filter(
                Q(title__icontains=self.query)
                | Q(abstract__icontains=self.query)
                | Q(keywords__icontains=self.query)
                | Q(authors__first_name__icontains=self.query)
                | Q(authors__last_name__icontains=self.query)
            ).distinct()
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


def _unique_article_slug(article, base):
    """Append -2, -3, ... to `base` until it doesn't collide with another article."""
    base = base or 'untitled-draft'
    slug = base
    n = 2
    while Article.objects.exclude(pk=article.pk).filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


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
    if not article.slug:
        article.slug = _unique_article_slug(article, slugify(article.title))

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
    if article.references:
        context['references_list'] = [
            line.strip() for line in article.references.strip().splitlines() if line.strip()
        ]
    return render(request, 'articles/article_detail.html', context)
