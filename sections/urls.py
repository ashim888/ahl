from django.urls import path

from . import views

app_name = 'sections'

urlpatterns = [
    path('sections/<slug:slug>/', views.SectionDetailView.as_view(), name='section_detail'),

    path('manage/sections/', views.SectionManageListView.as_view(), name='manage_section_list'),
    path('manage/sections/new/', views.SectionCreateView.as_view(), name='manage_section_create'),
    path('manage/sections/<int:pk>/edit/', views.SectionUpdateView.as_view(), name='manage_section_update'),
    path('manage/sections/<int:pk>/move/<str:direction>/', views.section_move, name='manage_section_move'),
    path('manage/sections/<int:pk>/delete/', views.SectionDeleteView.as_view(), name='manage_section_delete'),
]
