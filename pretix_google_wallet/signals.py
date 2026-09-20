from collections import OrderedDict

from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import (
    event_copy_data, register_global_settings, register_ticket_outputs,
)
from pretix.control.signals import nav_event_settings, nav_organizer

from .client import SUBEVENT_HERO_PREFIX
from .forms import credential_fields


@receiver(event_copy_data, dispatch_uid="pretix_google_wallet_drop_copied_hero_images")
def drop_copied_subevent_hero_images(sender, other, **kwargs):
    """
    Event.copy_data_from() copies every setting verbatim, but per-date hero images are
    keyed on the source event's subevent ids and dates are not copied at all. Left in
    place they would point at nothing, and because the value is a raw file reference the
    two events would share one file.
    """
    for key in [s.key for s in sender.settings._objects.all() if s.key.startswith(SUBEVENT_HERO_PREFIX)]:
        sender.settings.delete(key)


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
