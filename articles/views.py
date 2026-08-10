from django.views.generic import TemplateView

from .models import Article


class HomeView(TemplateView):
    """Journal homepage: hero banner, featured articles, latest news.

    Full article list/detail/search views land in Phase 3 (see ROADMAP.md);
    this is the Phase 1 placeholder-content homepage.
    """

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
