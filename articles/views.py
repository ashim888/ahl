from django.db.models import Q
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView, TemplateView

from .models import Article


class HomeView(TemplateView):
    """Journal homepage: hero banner, featured articles, latest news."""

    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        published = Article.objects.filter(status=Article.Status.PUBLISHED)
        context['featured_articles'] = published.exclude(
            article_type=Article.ArticleType.NEWS_COMMENTARY,
        ).order_by('-publication_date')[:5]
        context['latest_news'] = published.filter(
            article_type=Article.ArticleType.NEWS_COMMENTARY,
        ).order_by('-publication_date')[:5]
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
        queryset = Article.objects.filter(status=Article.Status.PUBLISHED).order_by('-publication_date')
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
        context['article_authors'] = self.object.articleauthor_set.select_related('user').order_by('order')
        context['show_full_text'] = self.object.access_type == Article.AccessType.OPEN_ACCESS
        if self.object.references:
            context['references_list'] = [
                line.strip() for line in self.object.references.strip().splitlines() if line.strip()
            ]
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
        queryset = Article.objects.filter(status=Article.Status.PUBLISHED).order_by('-publication_date')
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
