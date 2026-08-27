from django.urls import path

from . import views

app_name = 'ads'

urlpatterns = [
    path('ads/<int:pk>/click/', views.ad_click, name='click'),

    # Editorial — Editor/EiC/Admin (see EDITORIAL_ROLES in views.py)
    path('manage/ads/', views.AdSlotListView.as_view(), name='manage_adslot_list'),
    path('manage/ads/analytics/', views.AdSlotAnalyticsOverviewView.as_view(), name='manage_ads_analytics'),
    path('manage/ads/new/', views.AdSlotCreateView.as_view(), name='manage_adslot_create'),
    path('manage/ads/<int:pk>/edit/', views.AdSlotUpdateView.as_view(), name='manage_adslot_update'),
    path('manage/ads/<int:pk>/delete/', views.AdSlotDeleteView.as_view(), name='manage_adslot_delete'),
    path('manage/ads/<int:pk>/analytics/', views.AdSlotAnalyticsView.as_view(), name='manage_adslot_analytics'),
    path('manage/ads/<int:pk>/toggle-active/', views.adslot_toggle_active, name='manage_adslot_toggle_active'),
    path(
        'manage/ads/settings/placeholder-zones/', views.ad_settings_update_placeholder_zones,
        name='manage_ad_settings_update_placeholder_zones',
    ),
]
