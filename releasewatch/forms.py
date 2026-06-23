from django import forms

from releasewatch.models import NotificationCadence, NotificationPreference


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
        widget=forms.RadioSelect,
    )

    class Meta:
        model = NotificationPreference
        fields = ["cadence", "email_enabled", "include_future_releases"]
