from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from editorial_board.models import EditorialBoardMember
from issues.models import Issue
from users.decorators import role_required
from users.models import User

from .content_templates import ARTICLE_TYPE_CONTENT_TEMPLATES
from .forms import ArticleForm
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
# §6.2 grants "Access admin: Yes" to Editor/EiC/Admin only.
EDITORIAL_ROLES = (User.Role.EDITOR, User.Role.EDITOR_IN_CHIEF, User.Role.ADMIN)


class ComingSoonView(TemplateView):
    """Pre-launch placeholder at "/" — see the routing note in articles/urls.py."""

    template_name = 'coming_soon.html'


class HomeView(TemplateView):
    """Journal homepage: hero story, latest news, opinion, research
    highlights, special issues, and an editorial board preview.
    """

    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        published = Article.objects.filter(status=Article.Status.PUBLISHED).order_by('-publication_date')

        hero_article = published.first()
        context['hero_article'] = hero_article
        exclude_pk = [hero_article.pk] if hero_article else []
        if hero_article:
            context['hero_authors'] = hero_article.articleauthor_set.select_related('user').order_by('order')

        # prefetch_related so article.articleauthor_set.all/.first in the
        # template read from cache instead of firing a query per article.
        author_prefetch = 'articleauthor_set__user'

        context['latest_news'] = published.filter(
            article_type=Article.ArticleType.NEWS_COMMENTARY,
        ).exclude(pk__in=exclude_pk).prefetch_related(author_prefetch)[:3]

        context['opinion_pieces'] = published.filter(
            article_type__in=OPINION_TYPES,
        ).exclude(pk__in=exclude_pk).prefetch_related(author_prefetch)[:3]

        context['research_highlights'] = published.filter(
            article_type__in=RESEARCH_TYPES,
        ).exclude(pk__in=exclude_pk).select_related('issue').prefetch_related(author_prefetch)[:2]

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
            '-publication_date',
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
    """Abstract and metadata are always public. Full-text body (html_content) is
    shown for open-access articles only — subscription articles stay gated behind
    the Phase 6 paywall regardless of whether html_content is populated.
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
        context['show_full_text'] = self.object.access_type == Article.AccessType.OPEN_ACCESS
        if self.object.references:
            context['references_list'] = [
                line.strip() for line in self.object.references.strip().splitlines() if line.strip()
            ]
        context['related_articles'] = Article.objects.filter(
            status=Article.Status.PUBLISHED, article_type=self.object.article_type,
        ).exclude(pk=self.object.pk).order_by('-publication_date')[:3]
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
        ).order_by('-publication_date')
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
        ).order_by('-publication_date').prefetch_related('articleauthor_set__user')
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
        if status:
            queryset = queryset.filter(status=status)
        if article_type:
            queryset = queryset.filter(article_type=article_type)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['article_types'] = Article.ArticleType.choices
        context['statuses'] = Article.Status.choices
        context['selected_type'] = self.request.GET.get('type', '')
        context['selected_status'] = self.request.GET.get('status', '')
        return context


class ArticleFormMixin:
    """Shared context for create/update — the per-type content-template
    picker rendered in articles/manage/article_form.html.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['content_templates'] = {str(k): v for k, v in ARTICLE_TYPE_CONTENT_TEMPLATES.items()}
        return context

    def get_success_url(self):
        return reverse('articles:manage_article_update', kwargs={'slug': self.object.slug})


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
        messages.success(self.request, f'"{form.instance.title}" created.')
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
        messages.success(self.request, f'"{form.instance.title}" updated.')
        return super().form_valid(form)


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
    article.access_type = Article.resolve_access_type(article.article_type, article.access_type)

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
        'show_full_text': article.access_type == Article.AccessType.OPEN_ACCESS,
        'preview_mode': True,
        'related_articles': [],
    }
    if article.references:
        context['references_list'] = [
            line.strip() for line in article.references.strip().splitlines() if line.strip()
        ]
    return render(request, 'articles/article_detail.html', context)
