import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from requests import ConnectionError

from pretix_google_wallet.client import (
    API_ROOT,
    GoogleWalletClient,
    GoogleWalletError,
    build_event_ticket_class,
    build_event_ticket_object,
    class_id,
    grouping_id,
    object_id,
    wallet_position_is_eligible,
)
from pretix_google_wallet.models import WalletResourceSync


class GoogleWalletClientTest(TestCase):
    def setUp(self):
        organizer = SimpleNamespace(pk=2, name="Theatre", settings=Mock())
        event_settings = Mock(locale="en", organizer_logo_image_inherit=False)
        event_settings.get.return_value = ""
        event = SimpleNamespace(
            pk=3,
            organizer=organizer,
            organizer_id=2,
            name="Festival",
            location="Main street 1\nPrague",
            date_from=datetime.datetime(2026, 8, 25, 18, tzinfo=datetime.UTC),
            date_to=None,
            date_admission=None,
            timezone=datetime.UTC,
            settings=event_settings,
        )
        occurrence = SimpleNamespace(
            pk=4,
            name="First show",
            location="Small theatre\nPrague",
            date_from=datetime.datetime(2026, 8, 26, 19, tzinfo=datetime.UTC),
            date_to=datetime.datetime(2026, 8, 26, 21, tzinfo=datetime.UTC),
            date_admission=datetime.datetime(2026, 8, 26, 18, 30, tzinfo=datetime.UTC),
        )
        order = SimpleNamespace(
            pk=9,
            code="ABCDE",
            secret="order-secret",
            event=event,
            locale="en",
            status="p",
        )
        self.position = SimpleNamespace(
            pk=5,
            order=order,
            subevent=occurrence,
            subevent_id=4,
            item=SimpleNamespace(name="Ticket"),
            variation="VIP",
            attendee_name="Ada Lovelace",
            canceled=False,
            blocked=None,
            seat_id=None,
            addon_to_id=None,
            positionid=1,
            secret="ticket-secret",
            web_secret="ticket-web-secret",
            valid_from=None,
            valid_until=None,
        )

    @patch("pretix_google_wallet.client.eventreverse_absolute", return_value="https://tickets.example/")
    @patch("pretix_google_wallet.client.get_seat")
    def test_mapping_uses_stable_ids_current_subevent_seat_and_exact_secret(self, get_seat, event_url):
        get_seat.return_value = SimpleNamespace(
            seat_label="7",
            seat_number="7",
            row_label="1",
            row_name="1",
            zone_name="Balcony",
        )

        ticket_class = build_event_ticket_class("123", self.position)
        ticket_object = build_event_ticket_object("123", self.position)

        self.assertEqual(class_id("123", self.position), "123.pretix_2_3_4")
        self.assertEqual(object_id("123", self.position), "123.pretix_2_3_5")
        self.assertEqual(grouping_id("123", self.position), "123.pretix_order_2_3_4_9")
        self.assertEqual(ticket_class["eventName"]["defaultValue"]["value"], "First show")
        self.assertEqual(ticket_class["venue"]["name"]["defaultValue"]["value"], "Small theatre")
        self.assertEqual(ticket_object["barcode"]["value"], "ticket-secret")
        self.assertEqual(ticket_object["reservationInfo"]["confirmationCode"], "ABCDE")
        self.assertEqual(ticket_object["groupingInfo"]["groupingId"], "123.pretix_order_2_3_4_9")
        self.assertEqual(ticket_object["seatInfo"]["row"]["defaultValue"]["value"], "1")
        self.assertEqual(ticket_object["seatInfo"]["seat"]["defaultValue"]["value"], "7")

        self.position.subevent = None
        self.position.subevent_id = None
        regular_class = build_event_ticket_class("123", self.position)
        self.assertEqual(regular_class["id"], "123.pretix_2_3_0")
        self.assertEqual(regular_class["eventName"]["defaultValue"]["value"], "Festival")

        self.position.canceled = True
        self.assertEqual(build_event_ticket_object("123", self.position)["state"], "INACTIVE")

        self.position.canceled = False
        self.position.order.status = "e"
        self.assertEqual(build_event_ticket_object("123", self.position)["state"], "EXPIRED")

    def test_inactive_positions_are_not_wallet_eligible(self):
        self.assertTrue(wallet_position_is_eligible(self.position, datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)))
        self.position.canceled = True
        self.assertFalse(wallet_position_is_eligible(self.position, datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)))

    @patch("pretix_google_wallet.client.eventreverse_absolute")
    def test_object_contains_ticket_and_order_links(self, event_url):
        event_url.side_effect = lambda event, name, kwargs=None: (
            f"https://tickets.example/{name}/{kwargs['order']}"
        )

        payload = build_event_ticket_object("123", self.position)

        self.assertEqual(
            [link["uri"] for link in payload["linksModuleData"]["uris"]],
            [
                "https://tickets.example/presale:event.order.position/ABCDE",
                "https://tickets.example/presale:event.order/ABCDE",
            ],
        )

    @patch("pretix_google_wallet.client.eventreverse_absolute", return_value="https://tickets.example/")
    @patch("pretix_google_wallet.client.default_storage.url", return_value="/media/wallet-logo.png")
    def test_explicit_logo_and_background_color(self, storage_url, event_url):
        self.position.order.event.settings.get.side_effect = lambda name, **kwargs: {
            "ticketoutput_googlewallet_logo_image": "file://wallet/logo.png",
            "ticketoutput_googlewallet_background_color": "#920c0b",
        }.get(name, "")

        payload = build_event_ticket_class("123", self.position)

        self.assertEqual(
            payload["logo"]["sourceUri"]["uri"],
            "https://tickets.example/media/wallet-logo.png",
        )
        self.assertEqual(payload["hexBackgroundColor"], "#920c0b")

    def test_different_subevents_get_different_classes_and_groups(self):
        second_data = self.position.subevent.__dict__.copy()
        second_data.update(pk=8, name="Second show")
        self.position.subevent = SimpleNamespace(**second_data)
        self.position.subevent_id = 8

        self.assertEqual(class_id("123", self.position), "123.pretix_2_3_8")
        self.assertEqual(grouping_id("123", self.position), "123.pretix_order_2_3_8_9")

    @patch("pretix_google_wallet.client.eventreverse_absolute", return_value="https://tickets.example/")
    @patch("pretix_google_wallet.client.default_storage.url", return_value="/media/hero.jpg")
    def test_hero_image_prefers_explicit_event_setting(self, storage_url, event_url):
        self.position.order.event.settings.get.side_effect = lambda name, **kwargs: (
            "file://wallet/hero.jpg" if name == "ticketoutput_googlewallet_hero_image" else ""
        )

        payload = build_event_ticket_class("123", self.position)

        self.assertEqual(payload["heroImage"]["sourceUri"]["uri"], "https://tickets.example/media/hero.jpg")

    @patch("pretix_google_wallet.client.eventreverse_absolute", return_value="https://tickets.example/")
    @patch("pretix_google_wallet.client.default_storage.url", return_value="/media/subevent-hero.jpg")
    def test_hero_image_prefers_subevent_setting(self, storage_url, event_url):
        self.position.order.event.settings.get.side_effect = lambda name, **kwargs: (
            "file://wallet/subevent-hero.jpg"
            if name == "ticketoutput_googlewallet_hero_image_subevent_4" else ""
        )

        payload = build_event_ticket_class("123", self.position)

        self.assertEqual(payload["heroImage"]["sourceUri"]["uri"], "https://tickets.example/media/subevent-hero.jpg")

    def test_upsert_updates_an_existing_resource(self):
        session = Mock()
        session.patch.return_value = SimpleNamespace(status_code=200)
        client = GoogleWalletClient("123", Mock(), session=session)

        client._upsert("eventTicketObject", {"id": "123.object", "state": "ACTIVE"})

        session.patch.assert_called_once_with(
            f"{API_ROOT}/eventTicketObject/123.object",
            json={"id": "123.object", "state": "ACTIVE"},
            timeout=15,
        )

    @patch("pretix_google_wallet.client.eventreverse_absolute", return_value="https://tickets.example/")
    def test_batch_upsert_reuses_one_class_for_same_subevent(self, event_url):
        session = Mock()
        session.patch.return_value = SimpleNamespace(status_code=404)
        session.post.return_value = SimpleNamespace(status_code=200)
        client = GoogleWalletClient("123", Mock(), session=session)
        second_data = self.position.__dict__.copy()
        second_data.update(pk=6, positionid=2)
        second = SimpleNamespace(**second_data)

        identifiers = client.ensure_tickets([self.position, second])

        self.assertEqual(identifiers, ["123.pretix_2_3_5", "123.pretix_2_3_6"])
        self.assertEqual(session.post.call_count, 3)

    @patch("pretix_google_wallet.client.eventreverse_absolute", return_value="https://tickets.example/")
    def test_cached_resources_skip_api_requests(self, event_url):
        session = Mock()
        session.patch.return_value = SimpleNamespace(status_code=404)
        session.post.return_value = SimpleNamespace(status_code=200)
        client = GoogleWalletClient("123", Mock(), session=session)

        client.ensure_ticket(self.position)
        session.reset_mock()
        client.ensure_ticket(self.position)

        session.post.assert_not_called()
        session.patch.assert_not_called()
        self.assertEqual(WalletResourceSync.objects.count(), 2)

    @patch("pretix_google_wallet.client.eventreverse_absolute", return_value="https://tickets.example/")
    def test_api_timings_are_logged_without_payload_data(self, event_url):
        session = Mock()
        session.patch.return_value = SimpleNamespace(status_code=404)
        session.post.return_value = SimpleNamespace(status_code=200)
        client = GoogleWalletClient("123", Mock(), session=session)

        with self.assertLogs("pretix_google_wallet.client", level="DEBUG") as logs:
            client.ensure_ticket(self.position)

        output = "\n".join(logs.output)
        self.assertIn("Google Wallet eventTicketClass POST:", output)
        self.assertIn("Google Wallet total API time:", output)
        self.assertNotIn("ticket-secret", output)

    @patch("pretix_google_wallet.client.eventreverse_absolute", return_value="https://tickets.example/")
    def test_changed_object_uses_patch_without_insert(self, event_url):
        session = Mock()
        session.post.return_value = SimpleNamespace(status_code=200)
        session.patch.side_effect = [
            SimpleNamespace(status_code=404),
            SimpleNamespace(status_code=404),
            SimpleNamespace(status_code=200),
        ]
        client = GoogleWalletClient("123", Mock(), session=session)

        client.ensure_ticket(self.position)
        session.reset_mock()
        self.position.attendee_name = "Grace Hopper"
        client.ensure_ticket(self.position)

        session.post.assert_not_called()
        session.patch.assert_called_once()

    def test_network_errors_are_safe(self):
        session = Mock()
        session.patch.side_effect = ConnectionError("offline")
        client = GoogleWalletClient("123", Mock(), session=session)

        with self.assertRaises(GoogleWalletError):
            client._upsert("eventTicketObject", {"id": "123.object"})

    @patch("pretix_google_wallet.client.google_jwt.encode", return_value=b"signed")
    def test_save_jwt_references_existing_object(self, encode):
        credentials = SimpleNamespace(service_account_email="wallet@example.com", signer=object())
        client = GoogleWalletClient("123", credentials, session=Mock())

        url = client.create_save_url("123.object", "tickets.example.com")

        self.assertEqual(url, "https://pay.google.com/gp/v/save/signed")
        claims = encode.call_args.args[1]
        self.assertEqual(claims["iss"], "wallet@example.com")
        self.assertEqual(claims["origins"], ["tickets.example.com"])
        self.assertEqual(claims["payload"], {"eventTicketObjects": [{"id": "123.object"}]})

    @patch("pretix_google_wallet.client.google_jwt.encode", return_value=b"signed")
    def test_save_jwt_contains_multiple_deduplicated_objects(self, encode):
        credentials = SimpleNamespace(service_account_email="wallet@example.com", signer=object())
        client = GoogleWalletClient("123", credentials, session=Mock())

        client.create_save_url(["123.one", "123.two", "123.one"], "tickets.example.com")

        claims = encode.call_args.args[1]
        self.assertEqual(
            claims["payload"],
            {"eventTicketObjects": [{"id": "123.one"}, {"id": "123.two"}]},
        )
