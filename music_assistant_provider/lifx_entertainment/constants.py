"""Config constants for the LIFX Lights Sync provider."""

from __future__ import annotations

from typing import Final

CONF_BROADCAST: Final[str] = "broadcast_address"
CONF_EXTRA_HOSTS: Final[str] = "extra_hosts"
CONF_DEVICES: Final[str] = "devices"
CONF_LIGHTS: Final[str] = "lights"
CONF_GROUPING: Final[str] = "grouping"
CONF_BRIGHTNESS: Final[str] = "brightness"
CONF_COLOR_MODE: Final[str] = "color_mode"
CONF_LIGHT_LATENCY_MS: Final[str] = "light_latency_ms"
CONF_TRANSITION_MS: Final[str] = "transition_ms"
CONF_POWER_ON: Final[str] = "power_on"

# Visualization modes; first entry is the default. Used to build the config
# options and to migrate away orphaned stored values from older versions.
COLOR_MODES: Final[tuple[str, ...]] = ("smooth", "ambient", "flashing", "energetic")
DEFAULT_COLOR_MODE: Final[str] = COLOR_MODES[0]

# Grouping of devices into light players; first entry is the default.
GROUPINGS: Final[tuple[str, ...]] = ("group", "all", "light")
DEFAULT_GROUPING: Final[str] = GROUPINGS[0]

DEFAULT_BROADCAST: Final[str] = "255.255.255.255"
DEFAULT_BRIGHTNESS: Final[int] = 100
# LIFX bulbs are reached over Wi-Fi without a bridge; their round trip plus the
# per-frame transition is a bit longer than a Hue bridge's DTLS stream.
DEFAULT_LIGHT_LATENCY_MS: Final[int] = 100
DEFAULT_TRANSITION_MS: Final[int] = 50
DEFAULT_POWER_ON: Final[bool] = True

DISCOVERY_TIMEOUT_S: Final[float] = 3.0
# Devices are re-discovered periodically so a DHCP lease change is picked up.
REDISCOVERY_INTERVAL_S: Final[float] = 600.0

# ---- Spectrum config requested from the Sendspin visualizer ----

# 17 mel bins over 20-20kHz: enough resolution to map distinct bands to lights
# while keeping the per-frame payload small (bin ~10 ≈ 3.5kHz is the musical
# ceiling, see _CHANNEL_BIN_MAX in the analyzer).
SPECTRUM_BINS: Final[int] = 17
SPECTRUM_SCALE: Final = "mel"
SPECTRUM_F_MIN: Final[int] = 20
SPECTRUM_F_MAX: Final[int] = 20000
