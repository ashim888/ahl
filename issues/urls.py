from django.urls import path

from . import views

app_name = 'issues'

urlpatterns = [
    path('issues/', views.IssueListView.as_view(), name='issue_list'),
    path('issues/<int:volume>/<int:number>/', views.IssueDetailView.as_view(), name='issue_detail'),
]
