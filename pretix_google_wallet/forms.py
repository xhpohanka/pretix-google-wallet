from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SettingsForm

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
