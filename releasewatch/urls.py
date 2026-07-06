from django.urls import path

from releasewatch import views

app_name = "releasewatch"

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/signup/<str:code>/", views.signup_with_invite, name="signup_with_invite"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("follows/", views.follow_list, name="follow_list"),
    path("follows/<int:follow_id>/remove/", views.remove_follow, name="remove_follow"),
    path("imports/", views.import_list, name="import_list"),
    path("settings/feeds/", views.feed_settings, name="feed_settings"),
    path(
        "settings/feeds/<int:token_id>/revoke/",
        views.revoke_feed_token,
        name="revoke_feed_token",
    ),
    path("settings/notifications/", views.notification_settings, name="notification_settings"),
    path(
        "imports/candidates/<int:candidate_id>/review/",
        views.review_import_candidate,
        name="review_import_candidate",
    ),
    path("imports/<int:run_id>/", views.import_detail, name="import_detail"),
    path("artists/search/", views.artist_search, name="artist_search"),
    path("artists/follow/", views.follow_artist, name="follow_artist"),
    path("artists/<int:artist_id>/", views.artist_detail, name="artist_detail"),
    path("feeds/<str:token>/rss/", views.rss_feed, name="rss_feed"),
    path("feeds/<str:token>/ical/", views.ical_feed, name="ical_feed"),
    path("releases/", views.release_list, name="release_list"),
    path("releases/<int:event_id>/", views.release_detail, name="release_detail"),
]
