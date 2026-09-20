from datetime import timedelta

from django.test import TestCase
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import Event, Organizer

from pretix_google_wallet.client import SUBEVENT_HERO_PREFIX


class EventCopyTest(TestCase):
    @scopes_disabled()
    def setUp(self):
        self.organizer = Organizer.objects.create(name="Dummy", slug="dummy")
        # A hybrid-level plugin only counts as active when it is enabled on both the
        # organizer and the event, so its signal receivers need both.
        self.organizer.plugins = "pretix_google_wallet"
        self.organizer.save(update_fields=["plugins"])
        self.event = Event.objects.create(
            organizer=self.organizer, name="Festival", slug="festival",
            date_from=now() + timedelta(days=30), has_subevents=True,
        )
        self.event.plugins = "pretix_google_wallet"
        self.event.save(update_fields=["plugins"])

    @scopes_disabled()
    def test_copying_an_event_drops_per_date_hero_images(self):
        # Event.copy_data_from() copies every setting verbatim, but these are keyed on
        # the source event's subevent ids and dates are not copied at all. Left in place
        # they point at nothing, and since the value is a raw file reference both events
        # would share one file.
        self.event.settings.set(f"{SUBEVENT_HERO_PREFIX}4321", "file://hero.png")
        self.event.settings.set("ticketoutput_googlewallet_hero_image", "file://shared.png")

        copy = Event.objects.create(
            organizer=self.organizer, name="Copy", slug="copy",
            date_from=now() + timedelta(days=60), has_subevents=True,
        )
        copy.copy_data_from(self.event)

        # Assert on the stored keys rather than on values: hierarkey resolves a
        # "file://" setting through the storage and reports a missing file as False,
        # which would hide whether the key itself is still there.
        keys = {s.key for s in copy.settings._objects.all()}
        self.assertNotIn(f"{SUBEVENT_HERO_PREFIX}4321", keys)
        # The event-wide image is not keyed on an id and is still inherited.
        self.assertIn("ticketoutput_googlewallet_hero_image", keys)
