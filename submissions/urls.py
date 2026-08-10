from django.urls import path

from . import views

app_name = 'submissions'

urlpatterns = [
    path('submit/', views.submit_step1, name='submit_step1'),
    path('submit/manuscript/', views.submit_step2, name='submit_step2'),
    path('submit/review/', views.submit_step3, name='submit_step3'),
    path('dashboard/', views.author_dashboard, name='author_dashboard'),
    path('submissions/<int:pk>/revision/', views.upload_revision, name='upload_revision'),
]
