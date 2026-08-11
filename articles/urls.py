from django.urls import path

from . import views

app_name = 'articles'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('articles/', views.ArticleListView.as_view(), name='article_list'),
    path('search/', views.SearchView.as_view(), name='search'),
    path('articles/<slug:slug>/', views.ArticleDetailView.as_view(), name='article_detail'),
    path(
        'articles/<slug:slug>/cite/<str:citation_format>/',
        views.article_citation, name='article_citation',
    ),

    # Editorial CRUD — Editor/EiC/Admin only (see EDITORIAL_ROLES in views.py)
    path('manage/articles/', views.ArticleManageListView.as_view(), name='manage_article_list'),
    path('manage/articles/new/', views.ArticleCreateView.as_view(), name='manage_article_create'),
    path('manage/articles/preview/', views.article_preview, name='manage_article_preview'),
    path('manage/articles/<slug:slug>/edit/', views.ArticleUpdateView.as_view(), name='manage_article_update'),
    path('manage/articles/<slug:slug>/delete/', views.ArticleDeleteView.as_view(), name='manage_article_delete'),
]
