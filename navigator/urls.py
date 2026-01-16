"""URL configuration for Navigator app."""

from django.urls import path

from . import views

app_name = 'navigator'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('run/extract/', views.run_extract, name='run_extract'),
    path('run/sync/', views.run_sync, name='run_sync'),
    path('run/discover/', views.run_discover, name='run_discover'),
    path('run/<int:run_id>/progress/', views.run_progress, name='run_progress'),
    path('run/<int:run_id>/cancel/', views.run_cancel, name='run_cancel'),
]
