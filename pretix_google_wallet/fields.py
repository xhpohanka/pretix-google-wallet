import json

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SECRET_REDACTED, SecretKeySettingsField


def validate_service_account(value):
    if not value or value == SECRET_REDACTED:
        return
    try:
        data = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(_("Enter a valid service account JSON document.")) from exc
    if data.get("type") != "service_account" or not data.get("client_email") or not data.get("private_key"):
        raise ValidationError(_("The JSON must contain a service account client email and private key."))


class SecretTextareaWidget(forms.Textarea):
    def __init__(self, attrs=None):
        attrs = {**(attrs or {}), "autocomplete": "new-password", "rows": 8}
        self._reflect_value = False
        super().__init__(attrs)

    def value_from_datadict(self, data, files, name):
        value = super().value_from_datadict(data, files, name)
        self._reflect_value = bool(value and value != SECRET_REDACTED)
        return value

    def get_context(self, name, value, attrs):
        if value and not self._reflect_value:
            value = SECRET_REDACTED
        return super().get_context(name, value, attrs)


class ServiceAccountField(SecretKeySettingsField):
    widget = SecretTextareaWidget
    default_validators = [validate_service_account]
