from django.urls import path

from . import views

app_name = 'issues'

urlpatterns = [
    path('issues/', views.IssueListView.as_view(), name='issue_list'),
    path('issues/<int:volume>/<int:number>/', views.IssueDetailView.as_view(), name='issue_detail'),

    path('manage/issues/', views.IssueManageListView.as_view(), name='manage_issue_list'),
    path('manage/issues/new/', views.IssueCreateView.as_view(), name='manage_issue_create'),
    path('manage/issues/<int:pk>/edit/', views.IssueUpdateView.as_view(), name='manage_issue_update'),
    path('manage/issues/<int:pk>/delete/', views.IssueDeleteView.as_view(), name='manage_issue_delete'),
]
