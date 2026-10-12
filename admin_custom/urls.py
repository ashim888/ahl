from django.urls import path

from . import analytics, reports, views

app_name = 'admin_custom'

urlpatterns = [
    path('', views.DashboardHomeView.as_view(), name='dashboard'),
    path('revenue/', views.RevenueOverviewView.as_view(), name='revenue'),
    path('revenue/training/', views.RevenueTrainingView.as_view(), name='revenue_training'),
    path('revenue/subscriptions/', views.RevenueSubscriptionsView.as_view(), name='revenue_subscriptions'),
    path('analytics/', analytics.OverviewView.as_view(), name='analytics'),
    path('analytics/readership/', analytics.ReadershipView.as_view(), name='analytics_readership'),
    path('analytics/subscriptions/', analytics.SubscriptionsView.as_view(), name='analytics_subscriptions'),
    path('analytics/ads/', analytics.AdsView.as_view(), name='analytics_ads'),
    path('analytics/newsletter/', analytics.NewsletterView.as_view(), name='analytics_newsletter'),
    path('analytics/export/', views.analytics_csv_export, name='analytics_csv_export'),
    path('keywords/', views.KeywordAnalyticsView.as_view(), name='keyword_analytics'),
    path('keywords/export/', views.keyword_analytics_csv_export, name='keyword_analytics_csv_export'),
    path('keywords/<int:pk>/', views.KeywordAnalyticsDetailView.as_view(), name='keyword_analytics_detail'),
    path('comments/', views.CommentModerationListView.as_view(), name='manage_comment_list'),
    path('reports/', reports.ReportListView.as_view(), name='manage_report_list'),
    path('reports/<int:pk>/handle/', reports.report_handle, name='manage_report_handle'),
    path('comments/<int:pk>/<str:action>/', views.comment_moderate, name='manage_comment_moderate'),
]
