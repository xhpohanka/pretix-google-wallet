from collections import OrderedDict

from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import register_global_settings, register_ticket_outputs
from pretix.control.signals import nav_event_settings, nav_organizer

from .forms import credential_fields


@receiver(register_ticket_outputs, dispatch_uid="pretix_google_wallet_ticket_output")
def register_ticket_output(sender, **kwargs):
    from .ticketoutput import GoogleWalletOutput

    return GoogleWalletOutput


@receiver(register_global_settings, dispatch_uid="pretix_google_wallet_global_settings")
def global_settings(sender, **kwargs):
    return OrderedDict(credential_fields())


@receiver(nav_organizer, dispatch_uid="pretix_google_wallet_nav_organizer")
def organizer_settings_navigation(sender, request, organizer, **kwargs):
    if not request.user.has_organizer_permission(
        organizer, "organizer.settings.general:write", request=request,
    ):
        return []
    url = resolve(request.path_info)
    return [{
        "label": _("Google Wallet"),
        "url": reverse(
            "plugins:pretix_google_wallet:settings",
            kwargs={"organizer": organizer.slug},
        ),
        "parent": reverse(
            "control:organizer.edit",
            kwargs={"organizer": organizer.slug},
        ),
        "active": (
            url.namespace == "plugins:pretix_google_wallet"
            and url.url_name == "settings"
        ),
    }]


@receiver(nav_event_settings, dispatch_uid="pretix_google_wallet_nav_event_settings")
def subevent_hero_navigation(sender, request, **kwargs):
    if not request.user.has_event_permission(
        request.organizer, request.event, "event.settings.general:write", request=request,
    ):
        return []
    return [{
        "label": _("Google Wallet hero images"),
        "url": reverse("plugins:pretix_google_wallet:subevent_hero", kwargs={
            "organizer": request.organizer.slug,
            "event": request.event.slug,
        }),
        "active": resolve(request.path_info).namespace == "plugins:pretix_google_wallet"
        and resolve(request.path_info).url_name == "subevent_hero",
    }]
