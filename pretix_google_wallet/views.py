import logging

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import FormView
from pretix.base.models import OrderPosition, Organizer
from pretix.base.timemachine import time_machine_now
from pretix.control.permissions import (
    EventPermissionRequiredMixin,
    OrganizerPermissionRequiredMixin,
)
from pretix.control.views.event import EventSettingsViewMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin
from pretix.helpers.http import redirect_to_url
from pretix.presale.views import EventViewMixin
from pretix.presale.views.order import OrderDetailMixin

from .client import GoogleWalletClient, GoogleWalletError, wallet_position_is_eligible
from .forms import GoogleWalletOrganizerSettingsForm, GoogleWalletSubeventHeroForm
from .ticketoutput import GoogleWalletOutput

logger = logging.getLogger(__name__)


def wallet_positions(order):
    allowed_ids = {position.pk for position in order.positions_with_tickets}
    positions = OrderPosition.objects.filter(
        order=order,
        pk__in=allowed_ids,
    ).select_related(
        "order",
        "order__event",
        "order__event__organizer",
        "item",
        "variation",
        "subevent",
        "seat",
        "addon_to__seat",
    )
    now = time_machine_now()
    return [
        position for position in positions
        if wallet_position_is_eligible(position, now)
    ]


class GoogleWalletSettingsView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, FormView
):
    model = Organizer
    permission = "organizer.settings.general:write"
    form_class = GoogleWalletOrganizerSettingsForm
    template_name = "pretix_google_wallet/organizer_settings.html"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_google_wallet:settings",
            kwargs={"organizer": self.request.organizer.slug},
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["obj"] = self.request.organizer
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        changed = set(form.changed_data)
        form.save()
        if changed:
            self.request.organizer.log_action(
                "pretix.organizer.settings",
                user=self.request.user,
                data={
                    "google_wallet_issuer_id": form.cleaned_data.get("google_wallet_issuer_id")
                    if "google_wallet_issuer_id" in changed
                    else None,
                    "google_wallet_service_account_changed": "google_wallet_service_account" in changed,
                },
            )
        messages.success(self.request, _("Your changes have been saved."))
        return super().form_valid(form)


class GoogleWalletSubeventHeroView(EventSettingsViewMixin, EventPermissionRequiredMixin, FormView):
    template_name = "pretix_google_wallet/subevent_hero.html"
    form_class = GoogleWalletSubeventHeroForm
    permission = "event.settings.general:write"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["event"] = self.request.event
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["hero_rows"] = context["form"].hero_rows()
        return context

    def get_success_url(self):
        return reverse(
            "plugins:pretix_google_wallet:subevent_hero",
            kwargs={
                "organizer": self.request.organizer.slug,
                "event": self.request.event.slug,
            },
        )

    @transaction.atomic
    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("The subevent hero images have been saved."))
        return super().form_valid(form)


class GoogleWalletSaveView(EventViewMixin, OrderDetailMixin, View):
    def get(self, request, *args, **kwargs):
        position = get_object_or_404(
            OrderPosition.objects.select_related(
                "order",
                "order__event",
                "order__event__organizer",
                "item",
                "variation",
                "subevent",
                "seat",
                "addon_to__seat",
            ),
            order=self.order,
            pk=kwargs["position"],
        )
        if (
            not GoogleWalletOutput(self.request.event).is_enabled
            or not self.order.ticket_download_available
            or position.pk not in {p.pk for p in wallet_positions(self.order)}
        ):
            raise Http404(_("Ticket download is not available."))
        if (
            self.request.event.settings.ticket_download_require_validated_email
            and self.order.sales_channel.type == "web"
            and not self.order.email_known_to_work
        ):
            raise Http404(_("Ticket download is not available."))

        try:
            client = GoogleWalletClient.from_event(self.request.event)
            identifier = client.ensure_ticket(position)
            origin = request.get_host().split(":", 1)[0]
            return redirect_to_url(client.create_save_url(identifier, origin))
        except GoogleWalletError:
            logger.exception("Google Wallet ticket generation failed for order %s", self.order.code)
            messages.error(
                request,
                _("The Google Wallet ticket could not be created. Please try again later."),
            )
            return redirect_to_url(self.get_order_url())


class GoogleWalletSaveAllView(EventViewMixin, OrderDetailMixin, View):
    def get(self, request, *args, **kwargs):
        positions = wallet_positions(self.order)
        if (
            not GoogleWalletOutput(self.request.event).is_enabled
            or not self.order.ticket_download_available
            or len(positions) < 2
        ):
            raise Http404(_("Ticket download is not available."))
        if (
            self.request.event.settings.ticket_download_require_validated_email
            and self.order.sales_channel.type == "web"
            and not self.order.email_known_to_work
        ):
            raise Http404(_("Ticket download is not available."))

        try:
            client = GoogleWalletClient.from_event(self.request.event)
            identifiers = client.ensure_tickets(positions)
            origin = request.get_host().split(":", 1)[0]
            return redirect_to_url(client.create_save_url(identifiers, origin))
        except GoogleWalletError:
            logger.exception("Google Wallet batch ticket generation failed for order %s", self.order.code)
            messages.error(
                request,
                _("The Google Wallet tickets could not be created. Please try again later."),
            )
            return redirect_to_url(self.get_order_url())
