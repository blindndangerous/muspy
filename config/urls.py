from django.contrib import admin
from django.urls import include, path

from releasewatch.views import health

urlpatterns = [
    path("", include("releasewatch.urls")),
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
]
