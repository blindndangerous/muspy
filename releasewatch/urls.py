from django.urls import path

from releasewatch import views

app_name = "releasewatch"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("follows/", views.follow_list, name="follow_list"),
    path("artists/<int:artist_id>/", views.artist_detail, name="artist_detail"),
    path("releases/", views.release_list, name="release_list"),
    path("releases/<int:event_id>/", views.release_detail, name="release_detail"),
]
