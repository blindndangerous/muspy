from django.urls import path

from releasewatch import views

app_name = "releasewatch"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("follows/", views.follow_list, name="follow_list"),
    path("imports/", views.import_list, name="import_list"),
    path(
        "imports/candidates/<int:candidate_id>/review/",
        views.review_import_candidate,
        name="review_import_candidate",
    ),
    path("imports/<int:run_id>/", views.import_detail, name="import_detail"),
    path("artists/search/", views.artist_search, name="artist_search"),
    path("artists/follow/", views.follow_artist, name="follow_artist"),
    path("artists/<int:artist_id>/", views.artist_detail, name="artist_detail"),
    path("releases/", views.release_list, name="release_list"),
    path("releases/<int:event_id>/", views.release_detail, name="release_detail"),
]
