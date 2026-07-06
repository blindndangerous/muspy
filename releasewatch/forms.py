from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from releasewatch.models import FeedToken, NotificationCadence, NotificationPreference

PLAIN_TEXT_IMPORT_MAX_CHARS = 20_000
PLAIN_TEXT_IMPORT_MAX_NON_EMPTY_LINES = 500
LISTENBRAINZ_TOKEN_MAX_CHARS = 4_096


class ArtistSearchForm(forms.Form):
    q = forms.CharField(
        label="Artist name or MusicBrainz ID",
        max_length=255,
        strip=True,
    )


class FollowArtistForm(forms.Form):
    mbid = forms.UUIDField(label="MusicBrainz artist ID")


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
        fields = ["cadence", "email_enabled", "include_future_releases"]


class FeedTokenForm(forms.Form):
    feed_type = forms.ChoiceField(choices=FeedToken.FeedType.choices)
    name = forms.CharField(max_length=100, required=False, strip=True)


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
