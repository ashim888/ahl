from django.urls import path, register_converter
from django.views.generic import RedirectView

from . import author_views, views
from .converters import ShortCodeConverter
from .feeds import LatestArticlesAtomFeed, LatestArticlesFeed

register_converter(ShortCodeConverter, 'shortcode')

app_name = 'articles'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    # The homepage lived here while "/" showed a pre-launch "coming soon"
    # page — kept as a permanent redirect so old links and bookmarks still land.
    path('index/', RedirectView.as_view(pattern_name='articles:home', permanent=True)),
    path('articles/', views.ArticleListView.as_view(), name='article_list'),
    path('videos/', views.VideoListView.as_view(), name='video_list'),
    path('corrections/', views.CorrectionListView.as_view(), name='correction_list'),
    path('archive/', views.ArchiveListView.as_view(), name='archive_list'),
    path('for-you/', views.ForYouView.as_view(), name='for_you'),
    path('reading-list/', views.ReadingListView.as_view(), name='reading_list'),
    path('search/', views.SearchView.as_view(), name='search'),
    path('search/suggest/', views.search_suggest, name='search_suggest'),
    path('keywords/autocomplete/', views.keyword_autocomplete, name='keyword_autocomplete'),
    path('keywords/<slug:slug>/follow/', views.keyword_follow_toggle, name='keyword_follow_toggle'),
    path('keywords/<int:pk>/click/', views.keyword_click, name='keyword_click'),
    path('feed/', LatestArticlesFeed(), name='latest_feed'),
    path('feed/atom/', LatestArticlesAtomFeed(), name='latest_feed_atom'),
    # Must come before <slug:slug> below — a bare short code (e.g. "3f2a4")
    # would otherwise match the slug converter too (it's a valid slug shape)
    # and 404 there, since a real slug is the full "title-slug-code" string,
    # never just the code alone. Django tries patterns in list order.
    path('articles/<shortcode:code>/', views.article_short_link, name='article_short_link'),
    path('articles/<slug:slug>/', views.ArticleDetailView.as_view(), name='article_detail'),
    # Numeric form first: the old user-id URLs keep redirecting. Author.save()
    # never generates an all-digit slug, so no author page is shadowed.
    path('authors/<int:pk>/', views.legacy_author_redirect, name='legacy_author_detail'),
    path('authors/<slug:slug>/', views.AuthorDetailView.as_view(), name='author_detail'),
    path(
        'articles/<slug:slug>/cite/<str:citation_format>/',
        views.article_citation, name='article_citation',
    ),
    path('articles/<slug:slug>/download/', views.article_download, name='article_download'),
    path('articles/<slug:slug>/bookmark/', views.article_bookmark_toggle, name='article_bookmark_toggle'),
    path('articles/<slug:slug>/gift/', views.article_gift_create, name='article_gift_create'),
    path('articles/<slug:slug>/gift/<str:gift_token>/', views.ArticleDetailView.as_view(), name='article_gift_view'),

    # Editorial CRUD — Editor/EiC/Admin only (see EDITORIAL_ROLES in views.py)
    path('manage/articles/', views.ArticleManageListView.as_view(), name='manage_article_list'),
    path('manage/articles/new/', views.ArticleCreateView.as_view(), name='manage_article_create'),
    path('manage/articles/preview/', views.article_preview, name='manage_article_preview'),
    path('manage/articles/autosave/', views.article_autosave, name='manage_article_autosave'),
    path(
        'manage/articles/related-autocomplete/', views.related_article_autocomplete,
        name='manage_related_article_autocomplete',
    ),
    path(
        'manage/articles/related-suggestions/', views.related_article_suggestions,
        name='manage_related_article_suggestions',
    ),
    path('manage/articles/<slug:slug>/edit/', views.ArticleUpdateView.as_view(), name='manage_article_update'),
    path('manage/articles/<slug:slug>/authors/', views.article_manage_authors, name='manage_article_authors'),
    # Author byline profiles — no login account needed (see author_views.py).
    path('manage/authors/search/', views.author_search, name='manage_author_search'),
    path('manage/authors/', author_views.AuthorManageListView.as_view(), name='manage_author_list'),
    path('manage/authors/new/', author_views.AuthorCreateView.as_view(), name='manage_author_create'),
    path('manage/authors/<int:pk>/edit/', author_views.AuthorUpdateView.as_view(), name='manage_author_update'),
    path('manage/authors/<int:pk>/toggle-active/', author_views.author_toggle_active, name='manage_author_toggle_active'),
    path('manage/authors/<int:pk>/link-account/', author_views.author_link_account, name='manage_author_link_account'),
    path('manage/accounts/<int:user_pk>/author-profile/', author_views.author_from_account, name='manage_author_from_account'),
    path('manage/articles/<slug:slug>/delete/', views.ArticleDeleteView.as_view(), name='manage_article_delete'),
    path('manage/articles/<slug:slug>/quick-publish/', views.article_quick_publish, name='manage_article_quick_publish'),
    path('manage/articles/<slug:slug>/corrections/add/', views.article_correction_add, name='manage_article_correction_add'),
    path('manage/corrections/<int:pk>/delete/', views.article_correction_delete, name='manage_article_correction_delete'),
    path('manage/articles/<slug:slug>/notes/add/', views.article_note_add, name='manage_article_note_add'),
    path('manage/notes/<int:pk>/delete/', views.article_note_delete, name='manage_article_note_delete'),
    path('manage/articles/<slug:slug>/history/', views.article_history, name='manage_article_history'),
    path('manage/revisions/<int:pk>/restore/', views.article_revision_restore, name='manage_article_revision_restore'),
]
