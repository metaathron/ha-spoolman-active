# Spoolman Active Spool (Moonraker) – Home Assistant Integration

Custom integration for Home Assistant that adds a button to every spool
device created by [Disane87/spoolman-homeassistant](https://github.com/Disane87/spoolman-homeassistant),
letting you set that spool as the active filament on a specific printer via
its Moonraker instance. It also adds a dedicated device per printer showing
live data about its currently active spool, a button to clear it, and a
dropdown to pick it, plus an optional shared QR-code "hub" that lets you set
a spool active by scanning a code stuck on the spool itself - all without
ever calling Spoolman's API directly; the data is read straight from the
entities the Spoolman integration already maintains in Home Assistant.

## Source project

<https://github.com/Disane87/spoolman-homeassistant>

Background discussion on tracking an "active spool" per printer:
<https://github.com/Disane87/spoolman-homeassistant/discussions/290>

---

## Installation

### Installation via HACS

1. Add this repository as a custom repository to HACS:

[![Add Repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=metaathron&repository=ha-spoolman-active&category=Integration)

2. Use HACS to install the integration.
3. Restart Home Assistant.
4. Set up the integration using the UI:

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=spoolman_active_spool)

### Manual Installation

1. Download the integration files from the GitHub repository.
2. Place the `custom_components/spoolman_active_spool` folder in the `custom_components` directory of Home Assistant.
3. Restart Home Assistant.
4. Set up the integration using the UI:

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=spoolman_active_spool)

## Setup

Adding the integration shows a menu with two kinds of entry - add as many
of each as you need:

### Printer

1. Go to Settings → Devices & Services → Add Integration → Spoolman Active
   Spool (Moonraker) → **Printer**.
2. Enter:
   - Printer name (shown in the buttons' label, e.g. "Set active on Voron 2.4")
   - Moonraker URL of that printer (e.g. `http://192.168.1.50:7125`)
   - Whether to verify the SSL certificate (turn off if Moonraker sits behind a reverse proxy with a self-signed certificate)
   - How often to poll Moonraker for the active spool_id (default 30s)
3. Add the integration again, once per additional printer - every spool then gets one extra button, one per printer.

The printer's name, URL, SSL verification and poll interval can be changed
later from the integration's **Reconfigure** option, without needing to
remove and re-add it. Renaming the printer also renames the buttons'
`entity_id`. The printer's slugified name (`<printer>` below - spaces →
underscores, diacritics stripped, e.g. "Voron 2.4" → `voron_24`) is what
identifies it in webhook URLs.

### QR links (webhook hub)

A single, optional entry (add the integration again, choose **QR links
(webhook)** - it only appears once, before it's been set up). It creates one
shared link/webhook and a QR-code image entity for every spool. Scanning a
spool's QR code opens a small, self-contained page showing that spool and a
button per configured printer; picking a printer applies it immediately.
Opening the link (e.g. a chat app's link preview) never changes anything by
itself - only submitting the printer choice does.

The page is mobile-first and responsive, and automatically follows
whichever **light or dark theme your browser/device** is set to
(`prefers-color-scheme`) - this is independent of Home Assistant's own
frontend theme, which a plain webhook response has no access to.

The page's **text defaults to English**; if Home Assistant's own configured
instance language (Settings → System → General) is Czech, the page switches
to Czech instead. This follows the Home Assistant instance's language, not
the browser's.

Configurable from the same menu:

- **Webhook ID** - part of the URL (`<webhook_id>` below), auto-generated but editable.
- **Local network only** - restrict the webhook to LAN requests.
- **Home Assistant address** - used to build the QR codes' URLs; leave empty
  to auto-detect from Home Assistant's own configured URL.

#### Two URL shapes, same result

Both shapes below lead to the same picker/apply page; which one to use
mostly depends on how you're generating the link (see "Printing labels"
further down).

**A. Query-string webhook - the primary, most-featured shape:**

```
.../api/webhook/<webhook_id>?spool_id=<spool_id>&printer=<printer>
```

| Parameter | Required? | Meaning | If missing (default) |
|---|---|---|---|
| `<webhook_id>` | yes (part of the path) | Identifies which hub entry - fixed per hub, set in its "Webhook ID" field. | - |
| `spool_id` | no | Integer spool id. | Switches to the **remove active spool** flow instead of "set" (no spool card shown, printer picker still shown). |
| `printer` | no | The target printer's slugified name (see above). | Shows the printer picker page instead of applying anything; the change only happens once the picker's form is submitted (POST). |

**B. Spoolman-compatible path - for stock Spoolman's built-in label printer:**

```
.../api/webhook/<webhook_id>/spool/show/<spool_id>?printer=<printer>
```

| Parameter | Required? | Meaning | If missing (default) |
|---|---|---|---|
| `<webhook_id>` | yes (part of the path) | Same as above. | - |
| `<spool_id>` | yes (part of the path) | Integer spool id. There is no "remove" equivalent for this shape - it always needs a spool id in the path; use shape A without `spool_id` for removing (e.g. via the `image.spoolman_qr_remove_active_spool` entity). | - |
| `printer` | no | Same meaning as in shape A. | Same as in shape A - shows the picker. |

Behaves identically to shape A from the picker onward (same printer list,
same POST-safety, same live "offline" hint) - it exists purely to match the
fixed URL shape stock Spoolman's own label printer generates.

> ⚠️ **Warning:** including `printer` makes that specific GET request
> side-effecting, unlike every other link on this page - only use links
> with `printer` in places that won't auto-fetch a preview (an NFC tag, a
> Home Assistant automation/script, a phone shortcut). Never paste one into
> a chat app or anywhere else that generates link previews.

## Printing labels

However you generate a code for a spool, it's always one of the two URL
shapes above - here are three ways to get it onto (or near) the physical
spool.

### Via stock Spoolman

Stock Spoolman has its own built-in label printer that can already produce
a QR code pointing elsewhere than its own web UI (Settings → pick "URL"
instead of the `web+spoolman:` prefix - [Donkie/Spoolman#461](https://github.com/Donkie/Spoolman/pull/461)).
It always builds the code as `<base_url>/spool/show/<spool_id>` - a fixed
shape, no query string, no printer selection built in.

1. In Spoolman, go to Settings → General → Base URL and set it to your
   webhook URL (shown by `sensor.spoolman_qr_webhook_url`, i.e.
   `http://<ha_host>/api/webhook/<webhook_id>`).
2. When printing a spool's label, switch "QR code link" to "URL".
3. Spoolman now prints codes pointing at shape B above - this integration
   answers there with the same picker as the main webhook.

### Via the Spoolman-NG fork

[Spoolman-NG](https://github.com/sherrmann/Spoolman-NG) supports a fully
custom URL template instead of Spoolman's fixed `/spool/show/<spool_id>`
suffix, so you can point it straight at shape A - the primary, most-featured
link:

```
...http://<ha_host>/api/webhook/<webhook_id>?spool_id={id}
...http://<ha_host>/api/webhook/<webhook_id>?spool_id={id}&printer=<printer>
```

This is the recommended shape whenever you have the choice, since it's what
this integration's own QR entities use too (remove flow, `printer=`
direct-apply links, etc. all work from it).

### NFC tags

Since both shapes above are plain URLs, you can write either one to an NFC
tag with any generic NFC-writing app (e.g. NFC Tools) instead of printing a
QR code - tapping a phone against the tag opens the same page a QR scan
would. This pairs especially well with a `printer=<printer>` direct-apply
link (see above): one tap applies the change immediately, no picker screen
at all. Writing a link to an NFC tag is a deliberate, one-time action - not
something that generates automatic link previews - so it's a safe place to
use those otherwise side-effecting links.

## Requirements

- The **Spoolman** integration (Disane87/spoolman-homeassistant) installed and
  configured, so spool devices already exist.
- Moonraker with the `[spoolman]` component configured
  (see [Moonraker docs](https://moonraker.readthedocs.io/en/latest/configuration/#spoolman)),
  reachable from Home Assistant over the network.
- The `qrcode` Python package (installed automatically) if you use the QR
  links hub.

---

## Devices & Entities

For every **existing** spool device from the Spoolman integration, it adds:

- `button.spoolman_spool_<spool_id>_set_active_<printer>` - "Set active on
  `<printer>`". Pressing it sends `POST /server/spoolman/spool_id` to that
  printer's Moonraker with the spool's id, setting it as the active spool
  for that printer (the same thing Moonraker's `SPOOLMAN_SET_ACTIVE_SPOOL`
  gcode macro does). One per configured printer.
- `image.spoolman_spool_<spool_id>_qr_code` - a QR code encoding
  `.../api/webhook/<webhook_id>?spool_id=<spool_id>` (shape A above), i.e.
  "set this spool active" on the webhook hub's page. Only created if the QR
  links hub is configured.

For every configured printer, it also creates one device ("Printer
`<printer>`") of its own, holding:

- `sensor.spoolman_active_<printer>_spool` and
  `sensor.spoolman_active_<printer>_spool_<suffix>` - one sensor per
  attribute Spoolman already tracks for the active spool (id, weight,
  used/remaining weight and length, price, material, vendor, color,
  filament temperatures, extra fields, ...). These mirror the Spoolman
  integration's own sensors for whichever spool is currently active - no
  extra polling, they update live via state-change events. Handy for
  automations, e.g. `sensor.spoolman_active_voron24_spool` for the active
  spool's id.
- `button.spoolman_active_<printer>_spool_clear` - "Clear active spool on
  `<printer>`", unsets the active spool on that printer
  (`POST /server/spoolman/spool_id` with `spool_id: null`).
- `select.spoolman_active_<printer>_spool` - dropdown of every known spool,
  labelled and sorted as "material - vendor - name #id". Picking an option sets
  it as the active spool on that printer; the dropdown also follows
  whatever is set active some other way (a macro, Mainsail, one of the
  per-spool buttons) once the next poll comes in.

The QR links hub creates:

- `sensor.spoolman_qr_webhook_url` - diagnostic sensor showing the base
  webhook URL (handy for building your own links or automations).
- `image.spoolman_qr_remove_active_spool` - one QR code, not tied to any
  particular spool, that opens the "remove active spool" picker (pick a
  printer, clear whatever spool is active on it) - the same flow as
  `button.spoolman_active_<printer>_spool_clear`, but reachable by scanning
  a code instead.

## Features

- Dynamic entity creation - spools added later by the Spoolman integration
  get a button (and QR code, if configured) automatically, without a restart.
- Automatic cleanup - when the Spoolman integration removes a spool device,
  Home Assistant removes the corresponding entities along with it.
- No direct calls to Spoolman's REST API - all spool data (sensors, the
  dropdown's labels, and the QR page) is read from entities the Spoolman
  integration already maintains in Home Assistant.
- Only one thing is polled per printer: Moonraker's `/server/spoolman/status`,
  at a configurable interval, just to learn which spool_id is currently active.
- Full configuration and reconfiguration from the UI, including the
  printer's name, Moonraker URL, SSL verification, poll interval, and the
  QR hub's webhook ID / local-only setting / base URL.
- QR-code "set active spool" page: mobile-first, responsive design that
  follows your browser/device's light or dark theme; a Spoolman-style reel
  icon tinted with the filament's colour (rendered as hard-edged bands/rings
  for multi-colour filaments, matching Spoolman's own `multi_color_hexes` +
  `multi_color_direction`); material/vendor/name shown up front, every other
  Spoolman field tucked behind a collapsible "more parameters" toggle; text
  defaults to English, switching to Czech if the Home Assistant instance is
  configured for it. Each printer button also shows a live "offline" hint (a
  quick, short-timeout check against that printer's Moonraker) if it can't
  currently be reached - informational only, the button stays clickable
  either way.

## Notes

- This is a standalone add-on integration - it doesn't modify or replace any
  files from the Spoolman integration, so updating Spoolman doesn't affect it.

---

## Support

If you find this integration useful, you can support the development:

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/metaathron)

---

## License

This project is licensed under the MIT License.

Copyright (c) 2026 [metaathron](https://github.com/metaathron/)

You are free to use, modify, and distribute this software in accordance with the MIT License.

If you find this project useful, attribution and a link back to the original repository are appreciated:
<https://github.com/metaathron/ha-spoolman-active>
