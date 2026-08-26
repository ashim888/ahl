from django.urls import path

from . import views

app_name = 'ads'

urlpatterns = [
    path('ads/<int:pk>/click/', views.ad_click, name='click'),

    # Editorial — Editor/EiC/Admin (see EDITORIAL_ROLES in views.py)
    path('manage/ads/', views.AdSlotListView.as_view(), name='manage_adslot_list'),
    path('manage/ads/new/', views.AdSlotCreateView.as_view(), name='manage_adslot_create'),
    path('manage/ads/<int:pk>/edit/', views.AdSlotUpdateView.as_view(), name='manage_adslot_update'),
    path('manage/ads/<int:pk>/analytics/', views.AdSlotAnalyticsView.as_view(), name='manage_adslot_analytics'),
    path('manage/ads/<int:pk>/toggle-active/', views.adslot_toggle_active, name='manage_adslot_toggle_active'),
    path(
        'manage/ads/settings/toggle-placeholder/', views.ad_settings_toggle_placeholder,
        name='manage_ad_settings_toggle_placeholder',
    ),
]
