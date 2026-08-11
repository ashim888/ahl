from django.urls import path

from . import views

app_name = 'admin_custom'

urlpatterns = [
    path('', views.DashboardHomeView.as_view(), name='dashboard'),
]
