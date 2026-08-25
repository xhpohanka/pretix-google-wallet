from collections import OrderedDict

from django.conf import settings
from django.templatetags.static import static
from django.utils.translation import gettext_lazy as _
from pretix.base.ticketoutput import BaseTicketOutput
from pretix.control.forms import ExtFileField
from pretix.multidomain.urlreverse import eventreverse_absolute

from .client import configured


def _static_asset(name):
    try:
        return static(name)
    except ValueError:
        # collectstatic may not have been run in development yet.
        return f"{settings.STATIC_URL.rstrip('/')}/{name}"


class GoogleWalletOutput(BaseTicketOutput):
    identifier = "googlewallet"
    verbose_name = _("Google Wallet event tickets")
    download_button_icon = "fa-google"
    download_button_text = _("Add to Google Wallet")
    multi_download_button_text = _("Add all to Google Wallet")
    long_download_button_text = _("Add to Google Wallet")
    multi_download_enabled = True
    preview_allowed = False

    # The per-position table is too narrow for the branded badge. Keep its
    # compact native pretix button and use the official asset where there is
    # enough room.
    download_button_image = None
    long_download_button_image = _static_asset(
        "pretix_google_wallet/add-to-google-wallet-cz.svg"
    )
    multi_download_button_image = _static_asset(
        "pretix_google_wallet/add-to-google-wallet-cz.svg"
    )
    download_button_new_window = True

    @property
    def is_enabled(self):
        return super().is_enabled and configured(self.event)

    @property
    def settings_form_fields(self):
        return OrderedDict(
            list(super().settings_form_fields.items())
            + [
                (
                    "hero_image",
                    ExtFileField(
                        label=_("Google Wallet hero image"),
                        help_text=_(
                            "Optional wide event image. It must be publicly reachable over HTTPS."
                        ),
                        ext_whitelist=settings.FILE_UPLOAD_EXTENSIONS_IMAGE,
                        max_size=settings.FILE_UPLOAD_MAX_SIZE_IMAGE,
                        required=False,
                    ),
                ),
            ]
        )

    def generate(self, position):
        url = eventreverse_absolute(
            self.event,
            "plugins:pretix_google_wallet:save",
            kwargs={
                "order": position.order.code,
                "secret": position.order.secret,
                "position": position.pk,
            },
        )
        return "google-wallet.url", "text/uri-list", url

    def generate_order(self, order):
        url = eventreverse_absolute(
            self.event,
            "plugins:pretix_google_wallet:save_all",
            kwargs={
                "order": order.code,
                "secret": order.secret,
            },
        )
        return "google-wallet-all.url", "text/uri-list", url
