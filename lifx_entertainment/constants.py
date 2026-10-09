"""Protocol constants for the LIFX LAN protocol."""

from __future__ import annotations

from enum import IntEnum
from typing import Final

LIFX_PORT: Final[int] = 56700
DEFAULT_BROADCAST: Final[str] = "255.255.255.255"

PROTOCOL_NUMBER: Final[int] = 1024
HEADER_SIZE: Final[int] = 36

# LIFX recommends no more than 20 messages per second per device.
MAX_MESSAGES_PER_SECOND: Final[int] = 20

# Kelvin sent alongside saturated colours; only matters as saturation approaches 0.
DEFAULT_KELVIN: Final[int] = 3500

# SetExtendedColorZones / StateExtendedColorZones carry a fixed 82-entry colour array.
EXTENDED_ZONES_PER_MESSAGE: Final[int] = 82
# StateMultiZone (legacy multizone) reports 8 zones per packet.
LEGACY_ZONES_PER_MESSAGE: Final[int] = 8

SERVICE_UDP: Final[int] = 1


class MessageType(IntEnum):
    """LIFX LAN message type identifiers."""

    GET_SERVICE = 2
    STATE_SERVICE = 3
    SET_POWER = 21
    GET_LABEL = 23
    STATE_LABEL = 25
    GET_VERSION = 32
    STATE_VERSION = 33
    ACKNOWLEDGEMENT = 45
    GET_GROUP = 51
    STATE_GROUP = 53
    LIGHT_GET = 101
    LIGHT_SET_COLOR = 102
    LIGHT_STATE = 107
    LIGHT_SET_POWER = 117
    STATE_UNHANDLED = 223
    SET_COLOR_ZONES = 501
    GET_COLOR_ZONES = 502
    STATE_ZONE = 503
    STATE_MULTI_ZONE = 506
    SET_EXTENDED_COLOR_ZONES = 510
    GET_EXTENDED_COLOR_ZONES = 511
    STATE_EXTENDED_COLOR_ZONES = 512


class ZoneApply(IntEnum):
    """Apply modes for (legacy) multizone set messages."""

    NO_APPLY = 0
    APPLY = 1
    APPLY_ONLY = 2
