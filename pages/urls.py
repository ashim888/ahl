from django.urls import path

from . import views

app_name = 'pages'

urlpatterns = [
    path('terms/', views.page, {'slug': 'terms'}, name='terms'),
    path('privacy/', views.page, {'slug': 'privacy'}, name='privacy'),
    path('faq/', views.page, {'slug': 'faq'}, name='faq'),
    path('refund-policy/', views.page, {'slug': 'refund-policy'}, name='refunds'),
    path('manage/pages/', views.PageListView.as_view(), name='manage_page_list'),
    path('manage/pages/<slug:slug>/edit/', views.PageUpdateView.as_view(), name='manage_page_update'),
]
