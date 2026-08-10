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
]
