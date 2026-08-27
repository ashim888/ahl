from django.urls import path

from . import views

app_name = 'newsletter'

urlpatterns = [
    path('newsletter/subscribe/', views.subscribe, name='subscribe'),
    path('newsletter/confirm/<str:token>/', views.confirm, name='confirm'),
    path('newsletter/unsubscribe/<str:token>/', views.unsubscribe, name='unsubscribe'),

    # Editorial — Editor/EiC/Admin (see EDITORIAL_ROLES in views.py)
    path('manage/newsletter/', views.IssueListView.as_view(), name='manage_issue_list'),
    path('manage/newsletter/compose/', views.IssueComposeView.as_view(), name='manage_issue_compose'),
    path('manage/newsletter/preview/', views.issue_preview, name='manage_issue_preview'),
    path('manage/newsletter/<int:pk>/retry/', views.issue_retry, name='manage_issue_retry'),
]
