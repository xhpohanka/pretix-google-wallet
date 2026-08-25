# pretix-google-wallet

Native Google Wallet Event Tickets for pretix.

The plugin registers a standard pretix ticket output. Every ticket with downloads
enabled gets an **Add to Google Wallet** action next to PDF or Passbook downloads.
Orders with more than one eligible ticket also get **Add all to Google Wallet**;
this uses one signed JWT containing references to all existing ticket objects.
Both actions work on desktop and redirect to Google's standard Wallet save flow.
The spacious order-level and single-ticket actions use Google's official Czech localized SVG asset from the
[Wallet brand guidelines](https://developers.google.com/wallet/generic/resources/brand-guidelines).
Compact per-ticket table actions keep Pretix's native button styling. Wallet actions open in a new browser tab so the
order page remains available.

## Setup

1. Enable the Google Wallet API in Google Cloud.
2. Create a JSON key for a service account.
3. Add the service account email as a user with **Developer** access in the
   Google Pay and Wallet console.
4. Copy the numeric issuer ID from the Wallet console.
5. Install and enable this plugin for the organizer and event.
6. Open the organizer's **Google Wallet** settings and enter the issuer ID.
7. Configure credentials either in the masked organizer/global service-account
   JSON setting, or by setting GOOGLE_APPLICATION_CREDENTIALS to a server-side
   JSON key file.
8. Enable the **Google Wallet event tickets** output in the event's ticket-output
   settings.
9. Optionally upload a wide **Google Wallet hero image** in that output's event
   settings. It is used before the event's Open Graph image. Only publicly
   reachable HTTPS images can be fetched by Google Wallet.
10. Optionally set a **Google Wallet logo** and **background color** in the
    same output settings. The event or inherited organizer branding is used
    when these fields are empty.
11. For event series, use **Event settings → Google Wallet hero images** to
    override the hero image for individual dates. Empty dates use the event and
    organizer fallbacks.

Never commit the service-account JSON file or private key.

## Data and IDs

- One EventTicketClass is shared by a normal event or a specific subevent.
- One EventTicketObject maps to exactly one pretix OrderPosition.
- Objects from one order and one event/subevent share a stable `groupingInfo.groupingId`,
  so Google Wallet shows them as one carousel without grouping separate orders.
- IDs use immutable database primary keys, so reopening an order updates the same
  Google resources instead of creating duplicates.
- The QR barcode value is exactly OrderPosition.secret; pretix check-in keeps
  using its existing validation mechanism.

Every click updates the class and object from current pretix data before producing
a short signed JWT which references the object ID. This keeps seat, time, venue,
event or inherited organizer logo, ticket-holder and cancellation state ready for
later synchronization without a core patch.

The class also uses the event background color, event/subevent venue and geo
coordinates when available. A specific hero image is preferred, followed by the
event Open Graph image and only then a deliberately marked large event/organizer
logo; small logos are not promoted to hero images.

Each Wallet object links back to the public Pretix ticket page and its order
page using the existing order/position secrets. No new validation or ticket URL
is introduced.

Canceled or blocked tickets map to Google Wallet's INACTIVE state; expired
tickets map to EXPIRED. Automatic background updates and push notifications are
intentionally outside the first version.

## Development

Install the plugin in editable mode and run pytest from this directory.

The order-level button is built on Pretix's existing `generate_order()` ticket
output hook. A small generic core extension lets outputs provide an image asset
and request a new browser tab; the plugin's endpoint performs the current
eligibility check again before issuing the multi-object JWT.
