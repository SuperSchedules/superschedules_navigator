"""URL configuration for Navigator."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('', include('navigator.urls')),
    path('admin/', admin.site.urls),
]
