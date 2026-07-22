# Spoolman Active Spool (Moonraker) – Home Assistant Integration

Custom integration for Home Assistant that adds a button to every spool
device created by [Disane87/spoolman-homeassistant](https://github.com/Disane87/spoolman-homeassistant),
letting you set that spool as the active filament on a specific printer via
its Moonraker instance. It also adds a dedicated device per printer showing
live data about its currently active spool, a button to clear it, and a
dropdown to pick it - all without ever calling Spoolman's API directly; the
data is read straight from the entities the Spoolman integration already
maintains in Home Assistant.

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

1. Go to Settings → Devices & Services
2. Click "Add Integration"
3. Select Spoolman Active Spool (Moonraker)
4. Enter:
   - Printer name (shown in the buttons' label, e.g. "Set active on Voron 2.4")
   - Moonraker URL of that printer (e.g. `http://192.168.1.50:7125`)
   - Whether to verify the SSL certificate (turn off if Moonraker sits behind a reverse proxy with a self-signed certificate)
   - How often to poll Moonraker for the active spool_id (default 30s)
5. Add the integration again, once per additional printer - every spool then gets one extra button, one per printer.

The printer's name, URL, SSL verification and poll interval can be changed
later from the integration's **Reconfigure** option, without needing to
remove and re-add it. Renaming the printer also renames the buttons'
`entity_id`.

## Requirements

- The **Spoolman** integration (Disane87/spoolman-homeassistant) installed and
  configured, so spool devices already exist.
- Moonraker with the `[spoolman]` component configured
  (see [Moonraker docs](https://moonraker.readthedocs.io/en/latest/configuration/#spoolman)),
  reachable from Home Assistant over the network.

---

## Devices & Entities

For every **existing** spool device from the Spoolman integration, it adds:

- `button.spoolman_spool_<id>_set_active_<printer>` - "Set active on
  `<printer>`". Pressing it sends `POST /server/spoolman/spool_id` to that
  printer's Moonraker with the spool's id, setting it as the active spool
  for that printer (the same thing Moonraker's `SPOOLMAN_SET_ACTIVE_SPOOL`
  gcode macro does).

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

## Features

- Dynamic button creation - spools added later by the Spoolman integration
  get a button automatically, without a restart.
- Automatic cleanup - when the Spoolman integration removes a spool device,
  Home Assistant removes the corresponding button along with it.
- No direct calls to Spoolman's REST API - all spool data (sensors and the
  dropdown's labels) is read from entities the Spoolman integration already
  maintains in Home Assistant.
- Only one thing is polled: Moonraker's `/server/spoolman/status`, at a
  configurable interval, just to learn which spool_id is currently active.
- Full configuration and reconfiguration from the UI, including the
  printer's name, Moonraker URL, SSL verification and poll interval.

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
