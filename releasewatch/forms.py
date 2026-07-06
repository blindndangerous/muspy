from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm

from releasewatch.models import FeedToken, NotificationCadence, NotificationPreference, UserProfile

PLAIN_TEXT_IMPORT_MAX_CHARS = 20_000
PLAIN_TEXT_IMPORT_MAX_NON_EMPTY_LINES = 500
LISTENBRAINZ_TOKEN_MAX_CHARS = 4_096


def _apply_accessible_field_attrs(form):
    for name, field in form.fields.items():
        described_by = []
        if field.help_text:
            described_by.append(f"id_{name}_helptext")
        if form.is_bound and form.errors.get(name):
            field.widget.attrs["aria-invalid"] = "true"
            described_by.append(f"id_{name}_error")
        if described_by:
            field.widget.attrs["aria-describedby"] = " ".join(described_by)


class ArtistSearchForm(forms.Form):
    q = forms.CharField(
        label="Artist name or MusicBrainz ID",
        max_length=255,
        strip=True,
    )


class FollowArtistForm(forms.Form):
    mbid = forms.UUIDField(label="MusicBrainz artist ID")


class RemoveFollowForm(forms.Form):
    pass


class StarredReleaseForm(forms.Form):
    pass


class ImportCandidateReviewForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            ("accept", "Accept"),
            ("ignore", "Ignore"),
            ("reject", "Reject"),
        ],
        widget=forms.RadioSelect,
    )


class PlainTextImportForm(forms.Form):
    artist_names = forms.CharField(
        label="Artist names",
        max_length=PLAIN_TEXT_IMPORT_MAX_CHARS,
        error_messages={
            "max_length": (
                f"Ensure this value has at most {PLAIN_TEXT_IMPORT_MAX_CHARS} characters."
            ),
        },
        strip=False,
        widget=forms.Textarea(attrs={"rows": 8}),
    )

    def clean_artist_names(self):
        artist_names = self.cleaned_data["artist_names"]
        non_empty_lines = [line for line in artist_names.splitlines() if line.strip()]
        if not non_empty_lines:
            raise forms.ValidationError("Enter at least one artist name.")
        if len(non_empty_lines) > PLAIN_TEXT_IMPORT_MAX_NON_EMPTY_LINES:
            raise forms.ValidationError(
                f"Enter {PLAIN_TEXT_IMPORT_MAX_NON_EMPTY_LINES} or fewer artist names.",
            )
        return artist_names


class LastFmImportForm(forms.Form):
    username = forms.CharField(label="Last.fm username", max_length=255, strip=True)


class ListenBrainzImportForm(forms.Form):
    username = forms.CharField(label="ListenBrainz username", max_length=255, strip=True)
    token = forms.CharField(
        label="ListenBrainz user token",
        max_length=LISTENBRAINZ_TOKEN_MAX_CHARS,
        error_messages={
            "max_length": (
                f"Ensure this value has at most {LISTENBRAINZ_TOKEN_MAX_CHARS} characters."
            ),
        },
        strip=True,
        widget=forms.PasswordInput,
    )


class NotificationPreferenceForm(forms.ModelForm):
    cadence = forms.ChoiceField(
        choices=NotificationCadence.choices,
        error_messages={"invalid_choice": "Choose a valid choice."},
        widget=forms.RadioSelect,
    )

    class Meta:
        model = NotificationPreference
        fields = [
            "cadence",
            "email_enabled",
            "include_future_releases",
            "include_albums",
            "include_singles",
            "include_eps",
            "include_live",
            "include_compilations",
            "include_remixes",
            "include_other_release_types",
        ]


class FeedTokenForm(forms.Form):
    feed_type = forms.ChoiceField(choices=FeedToken.FeedType.choices)
    name = forms.CharField(max_length=100, required=False, strip=True)


class AccountSettingsForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        help_text="Used for account and notification email.",
    )
    timezone = forms.CharField(
        label="Time zone",
        max_length=64,
        help_text="Use an IANA time zone name, such as UTC or America/Denver.",
    )
    country = forms.CharField(
        label="Country",
        max_length=2,
        required=False,
        help_text="Optional two-letter country code, such as US or GB.",
    )

    def __init__(self, *args, user, profile: UserProfile, **kwargs):
        self.user = user
        self.profile = profile
        initial = {
            "email": user.email,
            "timezone": profile.timezone,
            "country": profile.country.upper(),
        }
        initial.update(kwargs.pop("initial", {}))
        super().__init__(*args, initial=initial, **kwargs)
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["timezone"].widget.attrs["autocomplete"] = "off"
        self.fields["country"].widget.attrs["autocomplete"] = "country"
        _apply_accessible_field_attrs(self)

    def clean_timezone(self):
        value = self.cleaned_data["timezone"].strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise forms.ValidationError(
                "Enter a valid IANA time zone, such as UTC or America/Denver."
            ) from error
        return value

    def clean_country(self):
        value = self.cleaned_data["country"].strip().upper()
        if value and (len(value) != 2 or not value.isalpha()):
            raise forms.ValidationError("Enter a two-letter country code.")
        return value

    def save(self):
        email_changed = self.user.email != self.cleaned_data["email"]
        self.user.email = self.cleaned_data["email"]
        self.user.save(update_fields=["email"])

        self.profile.timezone = self.cleaned_data["timezone"]
        self.profile.country = self.cleaned_data["country"]
        update_fields = ["timezone", "country"]
        if email_changed:
            self.profile.email_verified_at = None
            update_fields.append("email_verified_at")
        self.profile.save(update_fields=update_fields)
        return self.user, self.profile


class AccountPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs["autocomplete"] = "current-password"
        self.fields["new_password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["new_password2"].widget.attrs["autocomplete"] = "new-password"
        _apply_accessible_field_attrs(self)


class AccountDeleteForm(forms.Form):
    confirm_delete = forms.CharField(
        label="Type DELETE to confirm account deletion",
        max_length=6,
        strip=True,
        help_text="This confirmation is required before your account can be deleted.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["confirm_delete"].widget.attrs["autocomplete"] = "off"
        _apply_accessible_field_attrs(self)

    def clean_confirm_delete(self):
        value = self.cleaned_data["confirm_delete"]
        if value != "DELETE":
            raise forms.ValidationError("Type DELETE to confirm.")
        return value


class InviteSignupForm(UserCreationForm):
    email = forms.EmailField(label="Email address")

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["autocomplete"] = "username"
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["password2"].widget.attrs["autocomplete"] = "new-password"

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user
