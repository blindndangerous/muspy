from datetime import date
from importlib import import_module
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from releasewatch.forms import NotificationPreferenceForm
from releasewatch.models import (
    Artist,
    Follow,
    Notification,
    NotificationCadence,
    NotificationPreference,
    ReleaseEvent,
    ReleaseGroup,
)

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-password"  # noqa: S105

RELEASE_TYPE_FIELDS = [
    "include_albums",
    "include_singles",
    "include_eps",
    "include_live",
    "include_compilations",
    "include_remixes",
    "include_other_release_types",
]


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=TEST_PASSWORD,
    )


def create_release_event(
    *,
    primary_type="Album",
    secondary_types=None,
    title="Release",
):
    artist = Artist.objects.create(mbid=uuid4(), name=f"{title} Artist")
    group = ReleaseGroup.objects.create(
        mbid=uuid4(),
        artist=artist,
        title=title,
        primary_type=primary_type,
        secondary_types=list(secondary_types or []),
    )
    return ReleaseEvent.objects.create(
        release_group=group,
        event_date=date(2026, 6, 22),
        date_precision="day",
    )


def test_notification_preference_release_type_filters_default_to_included():
    user = create_user()

    preference = NotificationPreference.objects.create(user=user)

    for field_name in RELEASE_TYPE_FIELDS:
        assert getattr(preference, field_name) is True


@pytest.mark.parametrize(
    ("field_name", "primary_type", "secondary_types"),
    [
        ("include_albums", "Album", []),
        ("include_singles", "Single", []),
        ("include_eps", "EP", []),
        ("include_live", "Album", ["Live"]),
        ("include_compilations", "Album", ["Compilation"]),
        ("include_remixes", "Album", ["Remix"]),
        ("include_other_release_types", "Audiobook", []),
    ],
)
def test_fanout_skips_release_event_when_matching_release_type_is_disabled(
    field_name,
    primary_type,
    secondary_types,
):
    event = create_release_event(
        primary_type=primary_type,
        secondary_types=secondary_types,
        title=field_name,
    )
    user = create_user(field_name)
    Follow.objects.create(user=user, artist=event.release_group.artist)
    NotificationPreference.objects.create(user=user, **{field_name: False})

    from releasewatch.notifications import fanout_release_event_notifications

    result = fanout_release_event_notifications(release_event=event)

    assert result.created_count == 0
    assert result.skipped_count == 1
    assert Notification.objects.count() == 0


@pytest.mark.parametrize("primary_type", ["", "Interview"])
def test_fanout_treats_blank_and_unknown_primary_types_as_other(primary_type):
    event = create_release_event(primary_type=primary_type, title=f"other-{primary_type}")
    user = create_user(f"other-{primary_type or 'blank'}")
    Follow.objects.create(user=user, artist=event.release_group.artist)
    NotificationPreference.objects.create(user=user, include_other_release_types=False)

    from releasewatch.notifications import fanout_release_event_notifications

    result = fanout_release_event_notifications(release_event=event)

    assert result.created_count == 0
    assert result.skipped_count == 1
    assert Notification.objects.count() == 0


def test_notification_preference_form_saves_release_type_filters():
    user = create_user()
    preference = NotificationPreference.objects.create(user=user)
    form = NotificationPreferenceForm(
        {
            "cadence": NotificationCadence.WEEKLY,
            "email_enabled": "on",
            "include_future_releases": "on",
            "include_albums": "on",
            "include_eps": "on",
            "include_compilations": "on",
            "include_other_release_types": "on",
        },
        instance=preference,
    )

    assert form.is_valid(), form.errors

    saved = form.save()
    assert saved.include_albums is True
    assert saved.include_singles is False
    assert saved.include_eps is True
    assert saved.include_live is False
    assert saved.include_compilations is True
    assert saved.include_remixes is False
    assert saved.include_other_release_types is True


def test_notification_settings_page_labels_release_type_checkboxes(client):
    user = create_user()
    client.force_login(user)

    response = client.get(reverse("releasewatch:notification_settings"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "<legend>Release types</legend>" in html
    for field_name, label in [
        ("include_albums", "Albums"),
        ("include_singles", "Singles"),
        ("include_eps", "EPs"),
        ("include_live", "Live releases"),
        ("include_compilations", "Compilations"),
        ("include_remixes", "Remixes"),
        ("include_other_release_types", "Other release types"),
    ]:
        assert f'id="id_{field_name}"' in html
        assert f'<label for="id_{field_name}">{label}:</label>' in html


def test_notification_release_type_filter_migration_defaults_to_included():
    migration = import_module("releasewatch.migrations.0006_notification_type_filters")
    add_fields = {
        operation.name: operation.field.default
        for operation in migration.Migration.operations
        if operation.__class__.__name__ == "AddField"
    }

    assert add_fields == {field_name: True for field_name in RELEASE_TYPE_FIELDS}
