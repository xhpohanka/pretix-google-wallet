from django import forms
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SettingsForm
from pretix.control.forms import ExtFileField

from .fields import ServiceAccountField

issuer_id_validator = RegexValidator(
    regex=r"^[0-9]+$",
    message=_("The Google Wallet issuer ID contains digits only."),
)


def credential_fields():
    return {
        "google_wallet_issuer_id": forms.CharField(
            label=_("Google Wallet issuer ID"),
            required=False,
            validators=[issuer_id_validator],
        ),
        "google_wallet_service_account": ServiceAccountField(
            label=_("Google service account JSON"),
            help_text=_(
                "Stored as a masked setting. Leave empty to use the "
                "GOOGLE_APPLICATION_CREDENTIALS environment variable."
            ),
            required=False,
        ),
    }


class GoogleWalletOrganizerSettingsForm(SettingsForm):
    google_wallet_issuer_id = credential_fields()["google_wallet_issuer_id"]
    google_wallet_service_account = credential_fields()["google_wallet_service_account"]


class GoogleWalletSubeventHeroForm(SettingsForm):
    def __init__(self, *args, event, **kwargs):
        self.event = event
        self.subevents = list(event.subevents.order_by("date_from", "pk"))
        super().__init__(*args, obj=event, **kwargs)
        from .client import subevent_hero_setting_key

        for subevent in self.subevents:
            self.fields[subevent_hero_setting_key(subevent)] = ExtFileField(
                label=str(subevent),
                help_text=_("Leave empty to use the event or organizer fallback."),
                ext_whitelist=settings.FILE_UPLOAD_EXTENSIONS_IMAGE,
                max_size=settings.FILE_UPLOAD_MAX_SIZE_IMAGE,
                required=False,
            )

    def hero_rows(self):
        from .client import subevent_hero_setting_key

        return [
            (subevent, self[subevent_hero_setting_key(subevent)])
            for subevent in self.subevents
        ]
