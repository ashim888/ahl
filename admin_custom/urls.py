from django.urls import path

from . import views

app_name = 'admin_custom'

urlpatterns = [
    path('', views.DashboardHomeView.as_view(), name='dashboard'),
    path('revenue/', views.RevenueOverviewView.as_view(), name='revenue'),
    path('revenue/training/', views.RevenueTrainingView.as_view(), name='revenue_training'),
    path('revenue/subscriptions/', views.RevenueSubscriptionsView.as_view(), name='revenue_subscriptions'),
    path('analytics/', views.AnalyticsView.as_view(), name='analytics'),
    path('analytics/export/', views.analytics_csv_export, name='analytics_csv_export'),
    path('keywords/', views.KeywordAnalyticsView.as_view(), name='keyword_analytics'),
    path('keywords/export/', views.keyword_analytics_csv_export, name='keyword_analytics_csv_export'),
    path('keywords/<int:pk>/', views.KeywordAnalyticsDetailView.as_view(), name='keyword_analytics_detail'),
    path('comments/', views.CommentModerationListView.as_view(), name='manage_comment_list'),
    path('comments/<int:pk>/<str:action>/', views.comment_moderate, name='manage_comment_moderate'),
]
