from django.urls import path, register_converter

from . import views
from .converters import ShortCodeConverter
from .feeds import LatestArticlesAtomFeed, LatestArticlesFeed

register_converter(ShortCodeConverter, 'shortcode')

app_name = 'articles'

urlpatterns = [
    # Root is a "coming soon" placeholder until launch — the real homepage stays
    # reachable at /index/ (and via {% url 'articles:home' %}, unchanged) so
    # editorial staff can still preview it. Swap these two paths when going live.
    path('', views.ComingSoonView.as_view(), name='coming_soon'),
    path('index/', views.HomeView.as_view(), name='home'),
    path('articles/', views.ArticleListView.as_view(), name='article_list'),
    path('search/', views.SearchView.as_view(), name='search'),
    path('keywords/autocomplete/', views.keyword_autocomplete, name='keyword_autocomplete'),
    path('feed/', LatestArticlesFeed(), name='latest_feed'),
    path('feed/atom/', LatestArticlesAtomFeed(), name='latest_feed_atom'),
    # Must come before <slug:slug> below — a bare short code (e.g. "3f2a4")
    # would otherwise match the slug converter too (it's a valid slug shape)
    # and 404 there, since a real slug is the full "title-slug-code" string,
    # never just the code alone. Django tries patterns in list order.
    path('articles/<shortcode:code>/', views.article_short_link, name='article_short_link'),
    path('articles/<slug:slug>/', views.ArticleDetailView.as_view(), name='article_detail'),
    path('authors/<int:pk>/', views.AuthorDetailView.as_view(), name='author_detail'),
    path(
        'articles/<slug:slug>/cite/<str:citation_format>/',
        views.article_citation, name='article_citation',
    ),
    path('articles/<slug:slug>/download/', views.article_download, name='article_download'),

    # Editorial CRUD — Editor/EiC/Admin only (see EDITORIAL_ROLES in views.py)
    path('manage/articles/', views.ArticleManageListView.as_view(), name='manage_article_list'),
    path('manage/articles/new/', views.ArticleCreateView.as_view(), name='manage_article_create'),
    path('manage/articles/preview/', views.article_preview, name='manage_article_preview'),
    path('manage/articles/autosave/', views.article_autosave, name='manage_article_autosave'),
    path('manage/articles/<slug:slug>/edit/', views.ArticleUpdateView.as_view(), name='manage_article_update'),
    path('manage/articles/<slug:slug>/authors/', views.article_manage_authors, name='manage_article_authors'),
    path('manage/articles/<slug:slug>/delete/', views.ArticleDeleteView.as_view(), name='manage_article_delete'),
    path('manage/articles/<slug:slug>/quick-publish/', views.article_quick_publish, name='manage_article_quick_publish'),
]
