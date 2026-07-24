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
`entity_id`.

### QR links (webhook hub)

A single, optional entry (add the integration again, choose **QR links
(webhook)** - it only appears once, before it's been set up). It creates one
shared link/webhook and a QR-code image entity for every spool. Scanning a
spool's QR code opens a small, self-contained page (dark theme, mobile
responsive) showing that spool and a button per configured printer; picking
a printer applies it immediately. Opening the link (e.g. a chat app's link
preview) never changes anything by itself - only submitting the printer
choice does.

Configurable from the same menu:

- **Webhook ID** - part of the URL, auto-generated but editable.
- **Local network only** - restrict the webhook to LAN requests.
- **Home Assistant address** - used to build the QR codes' URLs; leave empty
  to auto-detect from Home Assistant's own configured URL.

The page's language follows Home Assistant's own configured language
(Settings → System → General): Czech if set to Czech, English otherwise.

#### Direct links (no picker, for your own automations/NFC tags/shortcuts)

Adding `&printer=<printer_stub>` to a webhook URL applies the change
immediately instead of showing the picker - `<printer_stub>` is the
printer's name, lowercased/slugified (spaces → underscores, diacritics
stripped), e.g. "Voron 2.4" → `voron_24`:

- `.../api/webhook/<id>?spool_id=<n>&printer=<stub>` - set that spool active
  on that printer.
- `.../api/webhook/<id>?printer=<stub>` - clear the active spool on that
  printer.

**This makes that specific GET request side-effecting**, unlike every other
link on this page - only use `printer=` links in places that won't
auto-fetch a preview (an NFC tag, a Home Assistant automation/script, a
phone shortcut). Never paste one into a chat app or anywhere else that
generates link previews.

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

- `button.spoolman_spool_<id>_set_active_<printer>` - "Set active on
  `<printer>`". Pressing it sends `POST /server/spoolman/spool_id` to that
  printer's Moonraker with the spool's id, setting it as the active spool
  for that printer (the same thing Moonraker's `SPOOLMAN_SET_ACTIVE_SPOOL`
  gcode macro does). One per configured printer.
- `image.spoolman_spool_<id>_qr_code` - a QR code linking straight to "set
  this spool active" on the webhook hub's page. Only created if the QR
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
- QR-code "set active spool" page: dark, mobile-first, responsive design;
  a Spoolman-style reel icon tinted with the filament's colour (rendered as
  hard-edged bands/rings for multi-colour filaments, matching Spoolman's own
  `multi_color_hexes` + `multi_color_direction`); material/vendor/name shown
  up front, every other Spoolman field tucked behind a collapsible "more
  parameters" toggle; follows Home Assistant's configured language (cs/en).

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
