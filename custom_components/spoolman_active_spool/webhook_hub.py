"""The shared QR-code webhook: registration, URL resolution, and the GET
(pick a printer, or apply directly) / POST (apply + show result) HTML pages.

Registered once, by the single hub config entry. Plain GET (no "printer"
query param) never changes anything - it just shows the spool and a list
of printers, each a submit button in one <form method="post">. This
matters because link previews (chat apps, browsers) issue GET requests
automatically when a link is shared; keeping bare GET side-effect-free
avoids an unintended spool change from a mere preview fetch.

Adding "&printer=<stub>" to the URL (stub = printer_object_id(entry.title),
e.g. "voron_24") skips the picker and applies the change immediately on
that GET - meant for building your own links (an NFC tag, an automation, a
phone shortcut), not for a QR code entity. Because it turns GET
side-effecting, a link that includes "printer" must never be pasted
somewhere that auto-generates a preview (chat apps, ...): treat it like a
POST, not like the plain spool_id-only links.
"""

from __future__ import annotations

import asyncio
import html
import itertools
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import aiohttp
from aiohttp import web

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    CONF_BASE_URL,
    CONF_ENTRY_TYPE,
    CONF_LOCAL_ONLY,
    CONF_WEBHOOK_ID,
    DEFAULT_LOCAL_ONLY,
    DOMAIN,
    ENTRY_TYPE_PRINTER,
)
from .moonraker import async_set_active_spool
from .spoolman_registry import (
    find_spool_device,
    printer_entries,
    printer_object_id,
    spool_meta_attrs,
    spool_source_entities,
)

_LOGGER = logging.getLogger(__name__)

# Modern, mobile-first theme that follows the device's light/dark setting
# (prefers-color-scheme) - Home Assistant's own frontend theme choice isn't
# readable from a plain webhook response (it's a per-user browser setting,
# not part of hass.config), so this is the closest practical equivalent and
# needs no configuration. The page is self-contained (no external
# fonts/JS/CSS) since it's served straight off the local HA instance.
_STYLE = """
:root {
  color-scheme: light dark;
  --bg: #0f1115;
  --bg-elevated: #1a1d24;
  --bg-elevated-2: #22262f;
  --border: #2a2e37;
  --text: #f2f3f5;
  --text-dim: #9aa0ab;
  --text-faint: #6b7078;
  --accent: #4f8cff;
  --success: #3ddc84;
  --error: #ff6b6b;
  --dashed-border: rgba(255,255,255,.32);
  --icon-ring: rgba(255,255,255,.08);
  --body-bg: radial-gradient(circle at top, #171a21, var(--bg) 60%);
  --radius-lg: 1.1rem;
  --radius-md: .85rem;
}
/* A single variable drives the body background (rather than two separate
   "body { background: ... }" rules) so light mode can't lose a cascade
   tie-break to the plain rule below just because of source order. */
@media (prefers-color-scheme: light) {
  :root {
    --bg: #eef0f3;
    --bg-elevated: #ffffff;
    --bg-elevated-2: #e7e9ed;
    --border: #d8dbe1;
    --text: #1c1f24;
    --text-dim: #565f6b;
    --text-faint: #848c98;
    --accent: #2f6fed;
    --success: #1f9d55;
    --error: #d9363e;
    --dashed-border: rgba(20,22,26,.28);
    --icon-ring: rgba(0,0,0,.08);
    --body-bg: #ffffff;
  }
}
* { box-sizing: border-box; }
html {
  font-size: 17px;
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}
body {
  margin: 0;
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--body-bg);
  color: var(--text);
  line-height: 1.45;
  padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
}
/* Full-bleed background; the inner column is what actually gets a max
   width, and it collapses to 100% on narrow (phone) screens. */
.page {
  width: 100%;
  max-width: 480px;
  margin: 0 auto;
  padding: 1.75rem 1.5rem 3rem;
}
@media (max-width: 480px) {
  .page { max-width: 100%; padding-left: 1.1rem; padding-right: 1.1rem; }
}
h1 { font-size: 1.4rem; font-weight: 700; margin: 0 0 1.25rem; letter-spacing: -.01em; }

/* Spool icon: Spoolman's own "reel" glyph, tinted with the filament's
   colour via currentColor, sitting on a neutral round badge. */
.spool-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--bg-elevated-2);
  box-shadow: inset 0 0 0 1px var(--icon-ring);
}
.spool-icon svg { width: 100%; height: 100%; display: block; }
.spool-icon.is-empty {
  background: transparent;
  border: 1.5px dashed var(--dashed-border);
}
.spool-icon.is-empty::before {
  content: "";
  width: 28%;
  height: 28%;
  border-radius: 50%;
  border: 1.5px dashed var(--dashed-border);
}
.spool-badge { width: 2.9rem; height: 2.9rem; }
.spool-hero { width: 96px; height: 96px; margin-bottom: .9rem; }

.spool-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.4rem 1.25rem;
  margin-bottom: 1.5rem;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.5);
}
.spool-card h2 { margin: .1rem 0 .15rem; font-size: 1.25rem; }
.primary { color: var(--text-dim); margin: .15rem 0; font-size: 1rem; }
.muted { color: var(--text-faint); font-size: .85rem; margin: .15rem 0 1rem; }
.muted-line { color: var(--text-dim); font-size: .95rem; }

/* Extra parameters (everything except material/vendor/name) start collapsed. */
details.params {
  text-align: left;
  margin-top: 1rem;
  border-top: 1px solid var(--border);
  padding-top: .25rem;
}
details.params summary {
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  padding: .6rem .1rem;
  font-size: .9rem;
  font-weight: 600;
  color: var(--text-dim);
}
details.params summary::-webkit-details-marker { display: none; }
details.params summary::after {
  content: "▾";
  color: var(--text-faint);
  font-size: 1.3rem;
  line-height: 1;
  transition: transform .2s ease;
}
details.params[open] summary::after { transform: rotate(180deg); }

table.details { width: 100%; border-collapse: collapse; margin-top: .25rem; font-size: .92rem; }
table.details th {
  text-align: left; font-weight: 500; color: var(--text-faint); padding: .45rem .6rem .45rem 0;
  white-space: nowrap;
}
table.details td { text-align: right; padding: .45rem 0; color: var(--text); word-break: break-word; }
table.details tr:not(:last-child) { border-bottom: 1px solid var(--border); }

.prompt {
  color: var(--text-dim); font-size: .82rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; margin: 1.2rem 0 .6rem;
}
.printer-list { display: flex; flex-direction: column; gap: .65rem; }
button.printer-btn {
  display: flex; align-items: center; gap: 1rem; width: 100%;
  padding: .8rem 1rem; border: 1px solid var(--border); border-radius: var(--radius-md);
  background: var(--bg-elevated); color: var(--text); font: inherit; text-align: left;
  cursor: pointer; box-shadow: 0 1px 2px rgba(0,0,0,.3);
  transition: transform .12s ease, background .12s ease, border-color .12s ease;
}
button.printer-btn:active { transform: scale(.98); background: var(--bg-elevated-2); }
button.printer-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.printer-text { display: flex; flex-direction: column; gap: .2rem; min-width: 0; flex: 1; }
.printer-name { font-weight: 600; }
.printer-current {
  font-size: .88rem; color: var(--text-dim);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.status {
  display: flex; align-items: flex-start; gap: .6rem; padding: .9rem 1rem;
  border-radius: var(--radius-md); margin-bottom: 1rem; font-weight: 600; font-size: .95rem;
}
.status.ok { background: rgba(61,220,132,.12); color: var(--success); border: 1px solid rgba(61,220,132,.3); }
.status.err { background: rgba(255,107,107,.12); color: var(--error); border: 1px solid rgba(255,107,107,.3); }

.err { color: var(--error); font-weight: 500; }
.ok { color: var(--success); font-weight: 500; }
"""

# Spoolman's own "reel" glyph (provided by the user), reused here so the
# webhook page matches Spoolman's own look instead of a generic dot.
_REEL_ICON_PATH = (
    "M12 2a10 10 0 0 0-2.148.26 10 10 0 0 0-1.315.386A10 10 0 0 0 7.672 3H7.67a10 "
    "10 0 0 0-1.295.752 10 10 0 0 0-.754.564 10 10 0 0 0-.98.938 10 10 0 0 "
    "0-.598.732 10 10 0 0 0-1.57 3.016 10 10 0 0 0-.315 1.314 10 10 0 0 "
    "0-.105.932v.008A10 10 0 0 0 2 12q0 .378.031.756l.002.012a10 10 0 0 0 .426 "
    "2.222 10 10 0 0 0 .38 1.014l.007.014.008.013q.218.497.488.967l.002.002a10 10 "
    "0 0 0 2.265 2.69 10 10 0 0 0 2.06 1.322h.003a10 10 0 0 0 "
    "2.15.746h.002q.514.114 1.035.174l.079.01q.529.057 1.062.058a10 10 0 0 0 "
    "2.148-.26 10 10 0 0 0 1.315-.386 10 10 0 0 0 .865-.354h.002a10 10 0 0 0 "
    "1.295-.752 10 10 0 0 0 .754-.564 10 10 0 0 0 .98-.938 10 10 0 0 0 .598-.732 "
    "10 10 0 0 0 1.57-3.016 10 10 0 0 0 .315-1.314 10 10 0 0 0 "
    ".105-.932v-.008q.04-.37.053-.744 0-.378-.031-.756l-.002-.012a10 10 0 0 "
    "0-.426-2.222 10 10 0 0 0-.38-1.014l-.007-.014-.008-.013a10 10 0 0 "
    "0-.488-.967L20.656 7a10 10 0 0 0-2.265-2.69 10 10 0 0 0-2.06-1.322h-.003a10 "
    "10 0 0 0-2.15-.746h-.002a10 10 0 0 0-1.114-.183A10 10 0 0 0 12 2m-1.299 "
    "2.25.256.148.11.063.066.039.433.25v1l-.433.25-.258.148v.002l-.174.1-.433-.25-.432-.25v-1l.268-.154zm2.598 "
    "0 .865.5v1l-.865.5-.865-.5v-1zm-4.46.426.13.074v1L8.537 "
    "6l-.433.25-.866-.5v-.172a8 8 0 0 1 1.602-.902m6.321 0a8 8 0 0 1 "
    "1.602.902v.172l-.658.38-.208.12-.865-.5v-1zM6.805 "
    "6.5l.865.5v1l-.865.5-.104-.06L5.94 8V7zm2.597 0 "
    ".866.5v1l-.127.074-.307.176-.432.25-.431-.25L8.537 8V7l.432-.25zM12 "
    "6.5l.865.5v1l-.12.07h-.003A4 4 0 0 0 12 8a4 4 0 0 0-.732.076L11.135 "
    "8V7l.761-.44zm2.598 0 "
    ".431.25.434.25v1l-.865.5-.432-.25-.434-.25V7l.434-.25zm2.597 0 "
    ".104.06.762.44v1l-.762.44-.104.06-.865-.5V7zM5.505 "
    "8.75l.866.5v1l-.865.5-.865-.5v-1zm2.599 0 .865.5v.14a4 4 0 0 0-.733 "
    "1.284l-.132.076-.56-.322-.306-.178v-1zm7.792 0 "
    ".866.5v1l-.434.25-.432.25-.12-.07a4 4 0 0 "
    "0-.657-1.174q-.043-.057-.088-.113V9.25l.432-.25zm2.598 0 "
    ".865.5v1l-.865.5-.207-.12-.658-.38v-1zM12 10a2 2 0 1 1 0 4 2 2 0 0 1 "
    "0-4m-7.793 1 .865.5v1l-.865.5-.135-.078A8 8 0 0 1 4 12a8 8 0 0 1 "
    ".072-.922zm2.598 0 "
    ".431.25.434.25v1l-.865.5-.104-.06-.762-.44v-1l.762-.44zm10.39 0 "
    ".104.06.762.44v1l-.762.44-.104.06-.431-.25-.434-.25v-1zm2.598 0 "
    ".135.078q.063.46.072.922a8 8 0 0 1-.072.922l-.135.078-.865-.5v-1zM5.506 "
    "13.25l.207.12.658.38v1l-.865.5-.865-.5v-1zm2.598 0 "
    ".12.07c.15.427.375.822.657 "
    "1.174q.043.057.088.113v.143l-.432.25-.433.25-.866-.5v-1l.434-.25zm7.792 0 "
    ".56.322.306.178v1l-.866.5-.865-.5v-.14a4 4 0 0 0 .621-1.008 4 4 0 0 0 "
    ".112-.276zm2.598 0 .865.5v1l-.865.5-.865-.5v-1zM6.804 "
    "15.5l.866.5v1l-.865.5-.104-.06L5.94 17v-1l.762-.44zm2.598 0 "
    ".432.25.434.25v1l-.434.25-.432.25-.431-.25-.434-.25v-1l.432-.25h.002zm5.196 "
    "0 .431.25.434.25v1l-.432.25-.433.25-.866-.5v-1l.127-.074.307-.176zm2.597 0 "
    ".104.06.762.44v1l-.866.5-.865-.5v-1zm-4.463.424.133.076v1l-.761.44-.104.06-.865-.5v-1l.12-.07h.003A4 "
    "4 0 0 0 12 16a4 4 0 0 0 .732-.076M8.104 17.75l.865.5v1l-.13.074a8 8 0 0 "
    "1-1.6-.902v-.172l.657-.38zm2.597 0 .865.5v1l-.865.5-.865-.5v-1zm2.598 0 "
    ".433.25.432.25v1l-.268.154-.597.346-.256-.148-.176-.102-.433-.25v-1l.433-.25.258-.148v-.002zm2.597 "
    "0 .866.5v.172a8 8 0 0 1-1.602.902l-.129-.074v-1l.432-.25z"
)

# Spoolman's color_hex can be RRGGBB, or RRGGBBAA for translucent filaments
# (also accept the short #RGB/#RGBA forms for safety).
_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{3,4}$|^#?[0-9a-fA-F]{6}$|^#?[0-9a-fA-F]{8}$")
_DEFAULT_ICON_COLOR = "#8a8f98"

# --- Localization: only hass.config.language decides (cs -> Czech, anything
# else -> English). Strings live in translations/webhook.<lang>.json (kept
# separate from webhook.py itself, and named "webhook.*" so they don't
# collide with HA's own translations/<lang>.json config-flow files in the
# same folder). The picker/result chrome comes from the "chrome" section;
# per-attribute detail-table row labels come from "details" and otherwise
# fall back to a prettified suffix name. ---

_TRANSLATIONS_DIR = Path(__file__).parent / "translations"


@lru_cache(maxsize=None)
def _load_strings(lang: str) -> dict:
    path = _TRANSLATIONS_DIR / f"webhook.{lang}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        _LOGGER.warning(
            "Spoolman Active Spool: could not load webhook translations from %s (%s)",
            path,
            err,
        )
        return {}


def _lang(hass: HomeAssistant) -> str:
    """"cs" if the HA instance is set to Czech, otherwise "en"."""
    configured = str(getattr(hass.config, "language", "") or "").lower()
    return "cs" if configured.startswith("cs") else "en"


def _t(lang: str, key: str, **kwargs) -> str:
    chrome = _load_strings(lang).get("chrome", {})
    text = chrome.get(key) or _load_strings("en").get("chrome", {}).get(key, key)
    return text.format(**kwargs) if kwargs else text


def _detail_label(suffix: str, lang: str) -> str:
    label = _load_strings(lang).get("details", {}).get(suffix)
    if label:
        return label
    return suffix.replace("_", " ").capitalize()


def resolve_base_url_value(
    hass: HomeAssistant, base_url: str | None, local_only: bool
) -> str | None:
    """The base URL to embed in QR codes / show in the diagnostic sensor.

    A manually configured base_url always wins. Otherwise it is resolved
    from Home Assistant's own network settings, restricted to an internal
    URL when local_only is on.
    """
    if base_url:
        return base_url.rstrip("/")

    try:
        return get_url(
            hass,
            allow_internal=True,
            allow_external=not local_only,
            allow_cloud=not local_only,
            prefer_external=not local_only,
        ).rstrip("/")
    except NoURLAvailableError:
        return None


def resolve_base_url(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """resolve_base_url_value(), reading its inputs from a hub config entry."""
    return resolve_base_url_value(
        hass,
        entry.data.get(CONF_BASE_URL),
        entry.data.get(CONF_LOCAL_ONLY, DEFAULT_LOCAL_ONLY),
    )


def webhook_full_url(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """The base webhook URL (no spool_id) - what the diagnostic sensor shows."""
    base = resolve_base_url(hass, entry)
    if base is None:
        return None
    return f"{base}{webhook.async_generate_path(entry.data[CONF_WEBHOOK_ID])}"


def spool_qr_url(hass: HomeAssistant, entry: ConfigEntry, spool_id: int) -> str | None:
    """The full per-spool URL to encode in that spool's QR code."""
    url = webhook_full_url(hass, entry)
    if url is None:
        return None
    return f"{url}?spool_id={spool_id}"


def _page(title: str, body: str, lang: str = "en") -> web.Response:
    text = (
        f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="theme-color" content="#0f1115" media="(prefers-color-scheme: dark)">'
        '<meta name="theme-color" content="#eef0f3" media="(prefers-color-scheme: light)">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f'<body><div class="page"><h1>{html.escape(title)}</h1>{body}</div></body></html>'
    )
    return web.Response(text=text, content_type="text/html")


# Suffixes already shown prominently (material/vendor/name/color) or not
# useful to a person scanning a code (the raw id) - left out of the
# generic details table below, which starts collapsed behind a toggle.
# multi_color_hexes/multi_color_direction mirror Spoolman's own API fields
# for multi-colour filaments (https://donkie.github.io/Spoolman/) - if the
# HA Spoolman integration exposes them under these exact suffixes they
# drive the banded icon below; if it doesn't expose them at all, the loop
# in _spool_info() simply never sets them and we fall back to the plain
# single colour.
_PRIMARY_SUFFIXES = {
    "material",
    "vendor",
    "filament_name",
    "filament_color_hex",
    "multi_color_hexes",
    "multi_color_direction",
    "id",
}

_MULTI_HEX_SPLIT_RE = re.compile(r"[,;/\s]+")

_gradient_ids = itertools.count()


def _normalize_color_hex(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not _HEX_COLOR_RE.match(value):
        return None
    return value if value.startswith("#") else f"#{value}"


def _parse_multi_hexes(value: str | None) -> list[str]:
    """"FF0000,00FF00" (Spoolman's multi_color_hexes format) -> ["#FF0000", "#00FF00"]."""
    if not value:
        return []
    colors = (_normalize_color_hex(part) for part in _MULTI_HEX_SPLIT_RE.split(value.strip()))
    return [c for c in colors if c]


def _spool_icon_html(
    color_hex: str | None,
    size_class: str,
    *,
    empty: bool = False,
    multi_hexes: list[str] | None = None,
    multi_direction: str | None = None,
) -> str:
    """Spoolman's reel glyph, tinted with the filament colour. Multi-colour
    filaments (2+ entries in multi_hexes) get hard-edged colour bands
    instead of a flat tint - radial ("coaxial", i.e. rings) or left-to-right
    ("longitudinal", the default). Empty/unknown spools get a dashed
    neutral outline."""
    classes = f"spool-icon {size_class}"

    if empty:
        # No glyph - just the dashed "empty holder" ring (outer flange +
        # inner hub via CSS), reads as a spool with nothing wound on it
        # instead of a dimmed, harder-to-parse copy of the full icon.
        return f'<span class="{classes} is-empty"></span>'

    colors = multi_hexes or []
    if len(colors) >= 2:
        gid = f"spool-grad-{next(_gradient_ids)}"
        n = len(colors)
        stops = "".join(
            f'<stop offset="{i / n * 100:.3f}%" stop-color="{html.escape(c)}"/>'
            f'<stop offset="{(i + 1) / n * 100:.3f}%" stop-color="{html.escape(c)}"/>'
            for i, c in enumerate(colors)
        )
        if multi_direction == "coaxial":
            gradient = f'<radialGradient id="{gid}" cx="50%" cy="50%" r="50%">{stops}</radialGradient>'
        else:
            gradient = f'<linearGradient id="{gid}" x1="0%" y1="0%" x2="100%" y2="0%">{stops}</linearGradient>'
        return (
            f'<span class="{classes}">'
            '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            f"<defs>{gradient}</defs>"
            f'<path d="{_REEL_ICON_PATH}" fill="url(#{gid})"></path>'
            "</svg></span>"
        )

    color = (colors[0] if colors else None) or _normalize_color_hex(color_hex) or _DEFAULT_ICON_COLOR
    return (
        f'<span class="{classes}" style="color:{html.escape(color)}">'
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">'
        f'<path d="{_REEL_ICON_PATH}"></path>'
        "</svg></span>"
    )


def _spool_info(hass: HomeAssistant, spool_id: int, lang: str) -> dict | None:
    """Collect material/vendor/name/colour + extra detail rows for a spool."""
    device = find_spool_device(dr.async_get(hass), spool_id)
    if device is None:
        return None

    meta = spool_meta_attrs(hass, device.id)

    rows: list[tuple[str, str]] = []
    ent_reg = er.async_get(hass)
    for source in spool_source_entities(ent_reg, device.id, spool_id):
        state = hass.states.get(source.entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            continue
        if source.suffix in _PRIMARY_SUFFIXES:
            continue
        unit = state.attributes.get("unit_of_measurement")
        value = f"{state.state} {unit}" if unit else state.state
        rows.append((_detail_label(source.suffix, lang), value))

    rows.sort(key=lambda r: r[0])
    name = meta.get("filament_name")
    return {
        "material": meta.get("filament_material") or "?",
        "vendor": meta.get("filament_vendor_name") or "?",
        "name": name or _t(lang, "spool_fallback_name", id=spool_id),
        "color_hex": meta.get("filament_color_hex"),
        "multi_hexes": _parse_multi_hexes(meta.get("filament_multi_color_hexes")),
        "multi_direction": meta.get("filament_multi_color_direction"),
        "rows": rows,
    }


def _spool_card_html(hass: HomeAssistant, spool_id: int, lang: str) -> tuple[str, str]:
    """Return (short label, full detail card html) for a spool, or an error."""
    info = _spool_info(hass, spool_id, lang)
    if info is None:
        err = _t(lang, "err_not_found", id=spool_id)
        return "", f"<p class='err'>{html.escape(err)}</p>"

    label = f"{info['material']} - {info['vendor']} - {info['name']}"
    icon_html = _spool_icon_html(
        info["color_hex"],
        "spool-hero",
        multi_hexes=info["multi_hexes"],
        multi_direction=info["multi_direction"],
    )

    rows = info["rows"]
    if rows:
        table_rows = "".join(
            f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in rows
        )
        # Collapsed by default (native <details>, no JS needed) - only
        # material/vendor/name stay visible above the fold.
        details_html = (
            '<details class="params">'
            f"<summary>{html.escape(_t(lang, 'more_params', n=len(rows)))}</summary>"
            f'<table class="details">{table_rows}</table>'
            "</details>"
        )
    else:
        details_html = ""

    card = (
        '<div class="spool-card">'
        f"{icon_html}"
        f"<h2>{html.escape(info['name'])}</h2>"
        f"<p class=\"primary\">{html.escape(info['material'])} · {html.escape(info['vendor'])}</p>"
        f"<p class=\"muted\">#{spool_id}</p>"
        f"{details_html}"
        "</div>"
    )
    return label, card


def _printer_button_html(hass: HomeAssistant, entry: ConfigEntry, lang: str) -> str:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    current_spool_id = coordinator.data.get("spool_id") if coordinator.data else None

    if current_spool_id is None:
        current_text = _t(lang, "empty_spool")
        icon_html = _spool_icon_html(None, "spool-badge", empty=True)
    else:
        info = _spool_info(hass, current_spool_id, lang)
        if info is None:
            current_text = _t(lang, "unknown_spool", id=current_spool_id)
            icon_html = _spool_icon_html(None, "spool-badge", empty=True)
        else:
            current_text = f"{info['material']} - {info['vendor']} - {info['name']}"
            icon_html = _spool_icon_html(
                info["color_hex"],
                "spool-badge",
                multi_hexes=info["multi_hexes"],
                multi_direction=info["multi_direction"],
            )

    return (
        '<button type="submit" class="printer-btn" '
        f'name="printer_entry_id" value="{html.escape(entry.entry_id)}">'
        f"{icon_html}"
        '<span class="printer-text">'
        f'<span class="printer-name">{html.escape(entry.title)}</span>'
        f'<span class="printer-current">{html.escape(current_text)}</span>'
        "</span>"
        "</button>"
    )


def _find_printer_by_stub(hass: HomeAssistant, stub: str) -> ConfigEntry | None:
    """Match a printer config entry by printer_object_id(entry.title)."""
    for entry in printer_entries(hass):
        if printer_object_id(entry.title) == stub:
            return entry
    return None


async def _handle_get(hass: HomeAssistant, request: web.Request) -> web.Response:
    lang = _lang(hass)
    raw_spool_id = request.query.get("spool_id")
    printer_stub = request.query.get("printer")

    spool_id: int | None = None
    if raw_spool_id is not None:
        try:
            spool_id = int(raw_spool_id)
        except ValueError:
            return _page(_t(lang, "title_error"), f"<p class='err'>{html.escape(_t(lang, 'err_invalid_id'))}</p>", lang)

    if printer_stub:
        # Deliberately side-effecting GET - see the module docstring for why
        # this is opt-in only (the "printer" param must be present) rather
        # than the default behaviour.
        entry = _find_printer_by_stub(hass, printer_stub)
        if entry is None:
            err = _t(lang, "err_invalid_printer")
            return _page(_t(lang, "title_error"), f"<p class='err'>{html.escape(err)}</p>", lang)
        return await _apply_spool_and_render(hass, entry, spool_id, lang)

    if raw_spool_id is None:
        # No spool_id, no printer -> "remove the active spool" picker, not an error.
        return _render_picker(
            hass, spool_id=None, title=_t(lang, "title_remove"), info_html="", lang=lang
        )

    _, info_html = _spool_card_html(hass, spool_id, lang)
    return _render_picker(
        hass, spool_id=spool_id, title=_t(lang, "title_set"), info_html=info_html, lang=lang
    )


def _render_picker(
    hass: HomeAssistant, spool_id: int | None, title: str, info_html: str, lang: str
) -> web.Response:
    printers = printer_entries(hass)
    if not printers:
        err = _t(lang, "err_no_printers")
        return _page(title, info_html + f"<p class='err'>{html.escape(err)}</p>", lang)

    buttons = "".join(_printer_button_html(hass, p, lang) for p in printers)
    hidden = f'<input type="hidden" name="spool_id" value="{spool_id}">' if spool_id is not None else ""
    prompt = _t(lang, "prompt_remove" if spool_id is None else "prompt_set")
    body = (
        f"{info_html}"
        f'<form method="post">{hidden}'
        f'<p class="prompt">{html.escape(prompt)}</p>'
        f'<div class="printer-list">{buttons}</div>'
        "</form>"
    )
    return _page(title, body, lang)


async def _handle_post(hass: HomeAssistant, request: web.Request) -> web.Response:
    lang = _lang(hass)
    form = await request.post()
    raw_spool_id = form.get("spool_id")

    spool_id: int | None = None
    if raw_spool_id not in (None, ""):
        try:
            spool_id = int(str(raw_spool_id))
        except ValueError:
            return _page(_t(lang, "title_error"), f"<p class='err'>{html.escape(_t(lang, 'err_invalid_id'))}</p>", lang)

    entry_id = form.get("printer_entry_id")
    entry = hass.config_entries.async_get_entry(str(entry_id)) if entry_id else None
    if (
        entry is None
        or entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_PRINTER) != ENTRY_TYPE_PRINTER
        or entry.state is not ConfigEntryState.LOADED
    ):
        err = _t(lang, "err_invalid_printer")
        return _page(_t(lang, "title_error"), f"<p class='err'>{html.escape(err)}</p>", lang)

    return await _apply_spool_and_render(hass, entry, spool_id, lang)


async def _apply_spool_and_render(
    hass: HomeAssistant, entry: ConfigEntry, spool_id: int | None, lang: str
) -> web.Response:
    """Set (or clear) the active spool on one printer and render the result
    page - the actual side-effecting step behind both the form POST and a
    direct GET that includes ?printer=<stub>."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if spool_id is not None:
        label, _ = _spool_card_html(hass, spool_id, lang)
    else:
        label = None

    try:
        await async_set_active_spool(
            hass, coordinator.moonraker_url, coordinator.verify_ssl, spool_id
        )
    except aiohttp.ClientError as err:
        action = _t(lang, "action_remove" if spool_id is None else "action_set")
        msg = _t(lang, "err_action_failed", action=action, err=str(err))
        status_html = f'<div class="status err">❌ {html.escape(msg)}</div>'
    else:
        if spool_id is None:
            msg = _t(lang, "ok_removed", printer=entry.title)
        else:
            spool_text = label or _t(lang, "unknown_spool", id=spool_id)
            msg = _t(lang, "ok_set", spool=spool_text, printer=entry.title)
        status_html = f'<div class="status ok">✅ {html.escape(msg)}</div>'

    await asyncio.sleep(2)
    await coordinator.async_request_refresh()

    current_spool_id = coordinator.data.get("spool_id") if coordinator.data else None
    if current_spool_id is not None:
        current_label, _ = _spool_card_html(hass, current_spool_id, lang)
        current_text = current_label or _t(lang, "unknown_spool", id=current_spool_id)
    else:
        current_text = _t(lang, "no_active_spool")

    current_line = _t(lang, "current_on", printer=entry.title, spool=current_text)
    body = f"{status_html}<p class=\"muted-line\">{html.escape(current_line)}</p>"
    return _page(_t(lang, "title_result"), body, lang)


async def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the hub's GET/POST webhook, and unregister it on unload."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    async def _handler(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        try:
            if request.method == "GET":
                return await _handle_get(hass, request)
            if request.method == "POST":
                return await _handle_post(hass, request)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Spoolman Active Spool: webhook handler failed")
            lang = _lang(hass)
            return _page(
                _t(lang, "title_error"),
                f"<p class='err'>{html.escape(_t(lang, 'err_unexpected'))}</p>",
                lang,
            )
        return web.Response(status=405)

    webhook.async_register(
        hass,
        DOMAIN,
        "Spoolman Active Spool QR",
        webhook_id,
        _handler,
        allowed_methods=["GET", "POST"],
        local_only=entry.data.get(CONF_LOCAL_ONLY, DEFAULT_LOCAL_ONLY),
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))
