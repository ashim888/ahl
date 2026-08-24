from django.urls import path

from . import views

app_name = 'admin_custom'

urlpatterns = [
    path('', views.DashboardHomeView.as_view(), name='dashboard'),
    path('revenue/', views.RevenueView.as_view(), name='revenue'),
    path('analytics/', views.AnalyticsView.as_view(), name='analytics'),
]
