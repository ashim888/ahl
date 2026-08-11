from django.urls import path

from . import views

app_name = 'editorial_board'

urlpatterns = [
    path('about/editorial-board/', views.EditorialBoardPublicView.as_view(), name='public_list'),

    path('manage/editorial-board/', views.BoardMemberManageListView.as_view(), name='manage_member_list'),
    path('manage/editorial-board/new/', views.BoardMemberCreateView.as_view(), name='manage_member_create'),
    path('manage/editorial-board/<int:pk>/edit/', views.BoardMemberUpdateView.as_view(), name='manage_member_update'),
    path('manage/editorial-board/<int:pk>/delete/', views.BoardMemberDeleteView.as_view(), name='manage_member_delete'),
]
