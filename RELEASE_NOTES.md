## v1.6.0

### New

- Snapmaker U1 toolhead support (read-only): real multi-toolhead printers exposing Snapmaker's own `print_task_config` object now get one `"<printer> - Tool <n>"` device per toolhead, each with the full per-attribute spool sensor set (same as the main "Aktivní cívka" sensors) plus a `binary_sensor` showing whether filament is actually fed through to that toolhead's nozzle right now. Single-toolhead printers are unaffected. There is currently no known way to *write* a spool assignment back per toolhead on Snapmaker's firmware, so this is visibility only - no select/button.

### Docs

- README clarifies that a stock Snapmaker U1 does **not** expose `AFC_lane`/`SET_SPOOL_ID` (despite earlier docs suggesting it might) and documents the new Tool N devices as the real, Snapmaker-specific mechanism.

### Upgrading

No action needed. If you have a multi-toolhead Snapmaker U1, reload the integration (or restart Home Assistant) to pick up the new `Tool <n>` devices.

## v1.5.0

### New

- The "Aktivní cívka" sensor (and each AFC lane's sensor) now carries *every* attribute Spoolman exposes for the active spool - weight, price, lot number, comment, dates, filament details, whatever it has - not just a fixed material/vendor/name/colour subset. Usable standalone without looking up the spool's own device.

### Fixed

- Devices could get a placeholder name (e.g. "? - ? - Cívka 18") right after a Home Assistant restart, only fixing itself after manually reloading the integration. This integration now waits for the Spoolman integration to finish loading first, so its entities' attributes are already populated by the time our devices get their names.
- Mirrored sensors with a timestamp/date device class (e.g. Spoolman's "registered" sensor) crashed every coordinator update with `'str' object has no attribute 'tzinfo'`. Mirrored values are now parsed into a real datetime/date object instead of copied as plain text.

### Upgrading

No action needed.

## v1.4.0

### New

- Optional Moonraker API key, for printers where Moonraker has "force_logins" (or no trusted clients) enabled and rejects unauthenticated requests. Set it on the printer's config/reconfigure screen; sent as an `X-Api-Key` header.
- Multi-extruder support: printers exposing Klipper "AFC_lane" objects (e.g. a 4-extruder Snapmaker U1 running the AFC-Lite stub or the full AFC-Klipper-Add-On) automatically get one full set of entities - dropdown, "set active"/"clear" buttons, sensor - per lane, plus a `&lane=` webhook parameter with a lane-picker step. Printers without AFC lanes are unaffected.

### Fixed

- Newly-added spool devices could show up unnamed under both "QR odkazy" and each printer's device list. Home Assistant 2026.8 stopped merging a device across multiple config entries; the per-spool "set active" button and QR code entities now get their own properly named device instead of silently relying on that merge.

### Known limitation

- AFC lane detection requires the printer's firmware to actually expose Klipper `AFC_lane <name>` objects and a `SET_SPOOL_ID` gcode macro. As of this release, stock Snapmaker U1 Extended Firmware does not expose either, even with "Spoolman Integration" enabled in Fluidd/Mainsail - lane entities simply won't appear until/unless the firmware adds it.

### Upgrading

No action needed. If you had spool devices showing up unnamed, reload this integration (or restart Home Assistant) - the fix applies automatically, but you may see an empty leftover "ghost" device for each previously-broken spool; safe to delete manually (Settings → Devices → open the empty one → Delete device).

## v1.3.0

### New

- The QR webhook page now automatically switches between a dark and a light look based on your phone/browser's own theme setting.
- Compatible with Spoolman's own label printing: stock Spoolman's built-in "print label as URL" feature, and the [Spoolman-NG](https://github.com/sherrmann/Spoolman-NG) fork, can generate codes that point straight at this integration (`.../spool/show/<spool_id>`) - see the README for setup.
- Each printer button on the picker page shows a live "offline" hint if that printer's Moonraker can't currently be reached (informational only - it doesn't stop you from trying).

### Fixed

- The webhook page's light theme had a dark patch behind the header that could make text hard to read.

### Docs

- README rewritten with a full parameter reference for both webhook URL shapes and a step-by-step guide to printing/writing labels (stock Spoolman, Spoolman-NG, NFC tags).

### Upgrading

No action needed - existing links and QR codes keep working exactly as before.
