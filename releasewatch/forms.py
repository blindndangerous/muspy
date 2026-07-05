from django import forms

from releasewatch.models import FeedToken, NotificationCadence, NotificationPreference


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
