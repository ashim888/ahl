from django.urls import path

from . import views

app_name = 'pitches'

urlpatterns = [
    # Any authenticated account — see PitchCreateView in views.py
    path('pitches/new/', views.PitchCreateView.as_view(), name='pitch_create'),
    path('pitches/mine/', views.MyPitchesListView.as_view(), name='my_pitches'),

    # Editorial — Editor/EiC/Admin (see EDITORIAL_ROLES in views.py)
    path('manage/pitches/', views.PitchQueueListView.as_view(), name='manage_pitch_queue'),
    path('manage/pitches/bulk-decide/', views.pitch_bulk_decide, name='manage_pitch_bulk_decide'),
    path('manage/pitches/<int:pk>/', views.pitch_detail, name='manage_pitch_detail'),
    path('manage/pitches/<int:pk>/<str:decision>/', views.pitch_decide, name='manage_pitch_decide'),
]
