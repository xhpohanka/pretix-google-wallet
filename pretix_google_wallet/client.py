import hashlib
import json
import logging
import os
import re
import time
from time import perf_counter
from urllib.parse import quote, urljoin, urlsplit

from django.core.files.storage import default_storage
from django.utils import timezone
from google.auth import jwt as google_jwt
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from pretix.base.models import Order
from pretix.base.pdf import get_seat
from pretix.base.timemachine import time_machine_now
from pretix.multidomain.urlreverse import eventreverse_absolute
from requests import RequestException

from .models import WalletResourceSync

API_ROOT = "https://walletobjects.googleapis.com/walletobjects/v1"
WALLET_SCOPE = "https://www.googleapis.com/auth/wallet_object.issuer"
SAVE_URL = "https://pay.google.com/gp/v/save/{}"
SUBEVENT_HERO_PREFIX = "ticketoutput_googlewallet_hero_image_subevent_"
logger = logging.getLogger(__name__)
_CREDENTIAL_CACHE = {}


class GoogleWalletError(Exception):
    pass


def _localized(value, locale):
    return {
        "defaultValue": {
            "language": (locale or "en").replace("_", "-"),
            "value": str(value),
        }
    }


def _local_iso(value, event):
    return value.astimezone(event.timezone).isoformat()


def _event_logo_url(event):
    names = ["ticketoutput_googlewallet_logo_image", "logo_image"]
    if event.settings.organizer_logo_image_inherit:
        names.append("organizer_logo_image")
    return _first_asset_url(event, names)


def _first_asset_url(event, names):
    for name in names:
        value = event.settings.get(name, as_type=str, default="")
        if not value:
            continue
        path = value[7:] if value.startswith("file://") else value
        url = urljoin(
            eventreverse_absolute(event, "presale:event.index"),
            default_storage.url(path),
        )
        if urlsplit(url).scheme == "https":
            return url


def subevent_hero_setting_key(subevent):
    return f"{SUBEVENT_HERO_PREFIX}{subevent.pk}"


def _event_hero_url(event, subevent=None):
    names = []
    if subevent is not None:
        names.append(subevent_hero_setting_key(subevent))
    names.extend(["ticketoutput_googlewallet_hero_image", "og_image"])
    if event.settings.logo_image_large:
        names.append("logo_image")
    if event.settings.organizer_logo_image_inherit and event.settings.organizer_logo_image_large:
        names.append("organizer_logo_image")
    return _first_asset_url(event, names)


def _event_color(event):
    for name in (
        "ticketoutput_googlewallet_background_color",
        "theme_color_background",
    ):
        value = event.settings.get(name, default="")
        if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return value
    return "#f5f5f5"


def _link_label(label, locale):
    if (locale or "").lower().startswith("cs"):
        return {"Ticket": "Vstupenka", "Order": "Objednávka"}[label]
    return label


def _ticket_links(position, locale):
    order = position.order
    event = order.event
    links = []
    if getattr(position, "web_secret", None):
        links.append({
            "uri": eventreverse_absolute(
                event,
                "presale:event.order.position",
                kwargs={
                    "order": order.code,
                    "position": position.positionid,
                    "secret": position.web_secret,
                },
            ),
            "localizedDescription": _localized(_link_label("Ticket", locale), locale),
        })
    if getattr(order, "secret", None):
        links.append({
            "uri": eventreverse_absolute(
                event,
                "presale:event.order",
                kwargs={"order": order.code, "secret": order.secret},
            ),
            "localizedDescription": _localized(_link_label("Order", locale), locale),
        })
    return links


def class_id(issuer_id, position):
    event = position.order.event
    occurrence = position.subevent_id or 0
    return f"{issuer_id}.pretix_{event.organizer_id}_{event.pk}_{occurrence}"


def object_id(issuer_id, position):
    event = position.order.event
    return f"{issuer_id}.pretix_{event.organizer_id}_{event.pk}_{position.pk}"


def grouping_id(issuer_id, position):
    event = position.order.event
    occurrence = position.subevent_id or 0
    return f"{issuer_id}.pretix_order_{event.organizer_id}_{event.pk}_{occurrence}_{position.order.pk}"


def wallet_position_is_eligible(position, now=None):
    now = now or time_machine_now()
    return (
        not position.canceled
        and not position.blocked
        and (position.valid_until is None or position.valid_until > now)
    )


def build_event_ticket_class(issuer_id, position):
    event = position.order.event
    occurrence = position.subevent or event
    locale = position.order.locale or event.settings.locale
    name = str(occurrence.name) or str(event.name)
    payload = {
        "id": class_id(issuer_id, position),
        "eventId": class_id(issuer_id, position),
        "issuerName": str(event.organizer.name),
        "eventName": _localized(name, locale),
        "dateTime": {
            "start": _local_iso(occurrence.date_from, event),
        },
        "reviewStatus": "UNDER_REVIEW",
    }
    if occurrence.date_admission:
        payload["dateTime"]["doorsOpen"] = _local_iso(occurrence.date_admission, event)
    if occurrence.date_to:
        payload["dateTime"]["end"] = _local_iso(occurrence.date_to, event)

    logo = _event_logo_url(event)
    if logo:
        payload["logo"] = {
            "sourceUri": {"uri": logo},
            "contentDescription": _localized(str(event.organizer.name), locale),
        }
    hero = _event_hero_url(event, position.subevent)
    if hero:
        payload["heroImage"] = {
            "sourceUri": {"uri": hero},
            "contentDescription": _localized(name, locale),
        }
    payload["hexBackgroundColor"] = _event_color(event)

    location = str(occurrence.location).strip() or str(event.location).strip()
    if location:
        lines = [line.strip() for line in location.splitlines() if line.strip()]
        payload["venue"] = {
            "name": _localized(lines[0], locale),
            "address": _localized("\n".join(lines[1:]) or lines[0], locale),
        }
    latitude = getattr(occurrence, "geo_lat", None)
    longitude = getattr(occurrence, "geo_lon", None)
    if latitude is None or longitude is None:
        latitude = getattr(event, "geo_lat", None)
        longitude = getattr(event, "geo_lon", None)
    if latitude is not None and longitude is not None:
        payload["locations"] = [{"latitude": latitude, "longitude": longitude}]
    return payload


def build_event_ticket_object(issuer_id, position):
    event = position.order.event
    order = position.order
    locale = order.locale or event.settings.locale
    ticket_type = str(position.item.name)
    if position.variation:
        ticket_type += f" - {position.variation}"

    if position.canceled or position.blocked or order.status == Order.STATUS_CANCELED:
        state = "INACTIVE"
    elif (
        order.status == Order.STATUS_EXPIRED
        or position.valid_until and position.valid_until < time_machine_now()
    ):
        state = "EXPIRED"
    else:
        state = "ACTIVE"

    payload = {
        "id": object_id(issuer_id, position),
        "classId": class_id(issuer_id, position),
        "state": state,
        "barcode": {
            "type": "QR_CODE",
            "value": position.secret,
            "alternateText": position.secret,
        },
        "reservationInfo": {
            "confirmationCode": order.code,
        },
        "ticketNumber": f"{order.code}-{position.positionid}",
        "ticketType": _localized(ticket_type, locale),
        "groupingInfo": {
            "groupingId": grouping_id(issuer_id, position),
            "sortIndex": position.positionid,
        },
    }
    if position.attendee_name:
        payload["ticketHolderName"] = str(position.attendee_name)

    seat = get_seat(position)
    if seat:
        seat_info = {}
        seat_value = seat.seat_label or seat.seat_number
        row_value = seat.row_label or seat.row_name
        if seat_value:
            seat_info["seat"] = _localized(seat_value, locale)
        if row_value:
            seat_info["row"] = _localized(row_value, locale)
        if seat.zone_name:
            seat_info["section"] = _localized(seat.zone_name, locale)
        if not seat_info:
            seat_info["seat"] = _localized(str(seat), locale)
        payload["seatInfo"] = seat_info

    validity = {}
    if position.valid_from:
        validity["start"] = {"date": _local_iso(position.valid_from, event)}
    if position.valid_until:
        validity["end"] = {"date": _local_iso(position.valid_until, event)}
    if validity:
        payload["validTimeInterval"] = validity
    links = _ticket_links(position, locale)
    if links:
        payload["linksModuleData"] = {"uris": links}
    return payload


def configured(event):
    return bool(
        event.organizer.settings.get("google_wallet_issuer_id", default="")
        and (
            event.organizer.settings.get("google_wallet_service_account", default="")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        )
    )


def load_credentials(event):
    raw = event.organizer.settings.get("google_wallet_service_account", default="")
    try:
        if raw:
            cache_material = raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True)
            cache_key = ("json", hashlib.sha256(cache_material.encode("utf-8")).hexdigest())
            if cache_key in _CREDENTIAL_CACHE:
                return _CREDENTIAL_CACHE[cache_key]
            info = raw if isinstance(raw, dict) else json.loads(raw)
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=[WALLET_SCOPE],
            )
            _CREDENTIAL_CACHE[cache_key] = credentials
            return credentials
        path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if path:
            stat = os.stat(path)
            cache_key = ("file", path, stat.st_mtime_ns, stat.st_size)
            if cache_key in _CREDENTIAL_CACHE:
                return _CREDENTIAL_CACHE[cache_key]
            credentials = service_account.Credentials.from_service_account_file(
                path, scopes=[WALLET_SCOPE],
            )
            _CREDENTIAL_CACHE[cache_key] = credentials
            return credentials
    except (OSError, TypeError, ValueError) as exc:
        raise GoogleWalletError("The Google Wallet service account configuration is invalid.") from exc
    raise GoogleWalletError("Google Wallet service account credentials are not configured.")


class GoogleWalletClient:
    def __init__(self, issuer_id, credentials, session=None):
        self.issuer_id = str(issuer_id)
        self.credentials = credentials
        self.session = session or AuthorizedSession(credentials)
        self.api_time = 0.0

    @classmethod
    def from_event(cls, event):
        issuer_id = event.organizer.settings.get("google_wallet_issuer_id", default="")
        if not issuer_id:
            raise GoogleWalletError("The Google Wallet issuer ID is not configured.")
        return cls(issuer_id, load_credentials(event))

    def _request(self, operation, resource, url, body):
        started = perf_counter()
        try:
            response = getattr(self.session, operation)(url, json=body, timeout=15)
        except RequestException:
            elapsed = perf_counter() - started
            self.api_time += elapsed
            logger.debug(
                "Google Wallet %s %s: %.2f s (request failed)",
                resource,
                operation.upper(),
                elapsed,
            )
            raise
        elapsed = perf_counter() - started
        self.api_time += elapsed
        logger.debug(
            "Google Wallet %s %s: %.2f s (HTTP %s)",
            resource,
            operation.upper(),
            elapsed,
            response.status_code,
        )
        return response

    def _upsert(self, resource, body):
        collection_url = f"{API_ROOT}/{resource}"
        try:
            resource_url = f"{collection_url}/{quote(body['id'], safe='')}"
            response = self._request("patch", resource, resource_url, body)
            if response.status_code == 404:
                response = self._request("post", resource, collection_url, body)
            if response.status_code == 409:
                response = self._request("patch", resource, resource_url, body)
        except RequestException as exc:
            raise GoogleWalletError("The Google Wallet API could not be reached.") from exc
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json().get("error", {}).get("message")
            except (TypeError, ValueError):
                detail = None
            raise GoogleWalletError(
                detail or f"Google Wallet API returned HTTP {response.status_code}."
            )

    @staticmethod
    def _payload_hash(payload):
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def _sync_resource(self, resource, payload):
        resource_id = payload["id"]
        payload_hash = self._payload_hash(payload)
        sync = WalletResourceSync.objects.filter(resource_id=resource_id).first()
        if sync and sync.payload_hash == payload_hash:
            logger.debug("Google Wallet %s skipped: payload unchanged", resource)
            return False
        self._upsert(resource, payload)
        if sync:
            sync.resource_type = resource
            sync.payload_hash = payload_hash
            sync.synced_at = timezone.now()
            sync.save(update_fields=("resource_type", "payload_hash", "synced_at"))
        else:
            WalletResourceSync.objects.create(
                resource_id=resource_id,
                resource_type=resource,
                payload_hash=payload_hash,
                synced_at=timezone.now(),
            )
        return True

    def ensure_tickets(self, positions):
        self.api_time = 0.0
        ticket_classes = {}
        ticket_objects = []
        for position in positions:
            ticket_class = build_event_ticket_class(self.issuer_id, position)
            ticket_classes[ticket_class["id"]] = ticket_class
            ticket_objects.append(build_event_ticket_object(self.issuer_id, position))
        try:
            for ticket_class in ticket_classes.values():
                self._sync_resource("eventTicketClass", ticket_class)
            for ticket_object in ticket_objects:
                self._sync_resource("eventTicketObject", ticket_object)
        finally:
            logger.debug("Google Wallet total API time: %.2f s", self.api_time)
        return [ticket_object["id"] for ticket_object in ticket_objects]

    def ensure_ticket(self, position):
        return self.ensure_tickets([position])[0]

    def create_save_url(self, object_identifiers, origin):
        if isinstance(object_identifiers, str):
            object_identifiers = [object_identifiers]
        object_identifiers = list(dict.fromkeys(object_identifiers))
        if not object_identifiers:
            raise GoogleWalletError("No Google Wallet tickets are available.")
        claims = {
            "iss": self.credentials.service_account_email,
            "aud": "google",
            "typ": "savetowallet",
            "iat": int(time.time()),
            "origins": [origin],
            "payload": {
                "eventTicketObjects": [{"id": identifier} for identifier in object_identifiers],
            },
        }
        started = perf_counter()
        token = google_jwt.encode(self.credentials.signer, claims)
        logger.debug("Google Wallet JWT generation: %.2f s", perf_counter() - started)
        if isinstance(token, bytes):
            token = token.decode("ascii")
        return SAVE_URL.format(token)
