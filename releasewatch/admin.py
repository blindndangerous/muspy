from django.contrib import admin

from .models import (
    Artist,
    ArtistAlias,
    EmailLog,
    FeedToken,
    Follow,
    ImportCandidate,
    ImportRun,
    Invite,
    Notification,
    NotificationPreference,
    ProviderAccount,
    Release,
    ReleaseEvent,
    ReleaseGroup,
    SyncState,
    UserProfile,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "timezone", "country", "email_verified_at"]
    search_fields = ["user__username", "user__email"]


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "cadence", "email_enabled", "include_future_releases"]
    list_filter = ["cadence", "email_enabled", "include_future_releases"]
    search_fields = ["user__username", "user__email"]


@admin.register(FeedToken)
class FeedTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "feed_type", "name", "revoked_at", "last_used_at"]
    list_filter = ["feed_type", "revoked_at"]
    search_fields = ["user__username", "user__email", "name"]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ["code", "created_by", "uses", "max_uses", "expires_at", "revoked_at"]
    search_fields = ["code", "created_by__username"]


class ArtistAliasInline(admin.TabularInline):
    model = ArtistAlias
    extra = 0


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ["name", "sort_name", "country", "last_refreshed_at"]
    search_fields = ["name", "sort_name", "mbid"]
    list_filter = ["artist_type", "country"]
    inlines = [ArtistAliasInline]


@admin.register(ArtistAlias)
class ArtistAliasAdmin(admin.ModelAdmin):
    list_display = ["artist", "name", "locale", "primary"]
    search_fields = ["name", "artist__name"]
    list_filter = ["locale", "primary"]


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ["user", "artist", "is_ignored", "created_at"]
    list_filter = ["is_ignored"]
    search_fields = ["user__username", "artist__name"]


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = ["user", "source", "status", "created_at", "updated_at"]
    list_filter = ["source", "status"]
    search_fields = ["user__username"]


@admin.register(ImportCandidate)
class ImportCandidateAdmin(admin.ModelAdmin):
    list_display = ["source_name", "artist", "review_state", "created_at", "reviewed_at"]
    list_filter = ["review_state"]
    search_fields = ["source_name", "source_identifier", "artist__name"]


@admin.register(ProviderAccount)
class ProviderAccountAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "provider",
        "external_username",
        "status",
        "last_imported_at",
        "updated_at",
    ]
    list_filter = ["provider", "status"]
    search_fields = ["user__username", "user__email", "external_username"]


@admin.register(ReleaseGroup)
class ReleaseGroupAdmin(admin.ModelAdmin):
    list_display = ["title", "artist", "primary_type", "first_release_date"]
    search_fields = ["title", "artist__name", "mbid"]
    list_filter = ["primary_type"]


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ["release_group", "country", "release_date", "status"]
    search_fields = ["release_group__title", "mbid"]
    list_filter = ["country", "status"]


@admin.register(ReleaseEvent)
class ReleaseEventAdmin(admin.ModelAdmin):
    list_display = [
        "release_group",
        "release",
        "country",
        "event_date",
        "visible",
        "notifiable",
    ]
    list_filter = ["visible", "notifiable", "date_precision"]
    search_fields = ["release_group__title", "release__mbid"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "release_event",
        "cadence_bucket",
        "status",
        "sent_at",
        "failed_at",
    ]
    list_filter = ["status"]
    search_fields = ["user__username", "release_event__release_group__title"]


@admin.register(SyncState)
class SyncStateAdmin(admin.ModelAdmin):
    list_display = ["artist", "sync_type", "status", "retry_after", "updated_at"]
    list_filter = ["sync_type", "status"]
    search_fields = ["artist__name"]


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["user", "message_type", "status", "created_at", "sent_at"]
    list_filter = ["message_type", "status"]
    search_fields = ["user__username", "provider_message_id"]
