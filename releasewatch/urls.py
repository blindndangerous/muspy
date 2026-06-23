from django.urls import path

from releasewatch import views

app_name = "releasewatch"

urlpatterns = [
    path("", views.home, name="home"),
    path("releases/", views.release_list, name="release_list"),
]
