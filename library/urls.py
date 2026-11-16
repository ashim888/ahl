from django.urls import path

from . import views

app_name = 'library'

urlpatterns = [
    path('library/', views.ResourceListView.as_view(), name='resource_list'),
    # Before library/<slug>/: "glossary" is reserved (Resource RESERVED_SLUGS).
    path('library/glossary/', views.glossary_list, name='glossary_list'),
    path('library/glossary/<slug:slug>/', views.glossary_detail, name='glossary_detail'),
    path('library/<slug:slug>/', views.ResourceDetailView.as_view(), name='resource_detail'),
    path('library/<slug:slug>/download/', views.resource_download, name='resource_download'),

    path('manage/library/', views.ResourceManageListView.as_view(), name='manage_resource_list'),
    path('manage/library/new/', views.ResourceCreateView.as_view(), name='manage_resource_create'),
    path('manage/library/<int:pk>/edit/', views.ResourceUpdateView.as_view(), name='manage_resource_update'),
    path('manage/library/<int:pk>/delete/', views.ResourceDeleteView.as_view(), name='manage_resource_delete'),

    path('manage/glossary/', views.GlossaryManageListView.as_view(), name='manage_glossary_list'),
    path('manage/glossary/new/', views.GlossaryCreateView.as_view(), name='manage_glossary_create'),
    path('manage/glossary/<int:pk>/edit/', views.GlossaryUpdateView.as_view(), name='manage_glossary_update'),
    path('manage/glossary/<int:pk>/delete/', views.GlossaryDeleteView.as_view(), name='manage_glossary_delete'),
]
