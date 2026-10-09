"""
Encoder/decoder for the LIFX LAN protocol.

Every message is a 36-byte little-endian header (frame, frame address, protocol header)
followed by a type-specific payload. Only the messages needed for discovery, state
snapshots and colour streaming are implemented.
"""

from __future__ import annotations

import colorsys
import struct
from dataclasses import dataclass
from typing import Final

from .constants import (
    DEFAULT_KELVIN,
    EXTENDED_ZONES_PER_MESSAGE,
    HEADER_SIZE,
    LEGACY_ZONES_PER_MESSAGE,
    PROTOCOL_NUMBER,
    MessageType,
    ZoneApply,
)
from .models import HSBK

_HEADER: Final = struct.Struct("<HHI8s6sBBQHH")
_HSBK: Final = struct.Struct("<HHHH")

_ADDRESSABLE: Final[int] = 1 << 12
_TAGGED: Final[int] = 1 << 13
_FLAG_RES_REQUIRED: Final[int] = 0x01
_FLAG_ACK_REQUIRED: Final[int] = 0x02

BROADCAST_TARGET: Final[bytes] = b"\x00" * 8


@dataclass(frozen=True, slots=True)
class Header:
    """A decoded LIFX message header."""

    size: int
    tagged: bool
    source: int
    target: bytes
    res_required: bool
    ack_required: bool
    sequence: int
    type: int

    @property
    def serial(self) -> str:
        """Return the device serial (MAC) as lowercase hex."""
        return self.target[:6].hex()


def encode_message(
    msg_type: int,
    payload: bytes = b"",
    *,
    source: int,
    sequence: int,
    target: bytes = BROADCAST_TARGET,
    res_required: bool = False,
    ack_required: bool = False,
) -> bytes:
    """
    Build a complete LIFX packet.

    :param msg_type: Message type number (see :class:`MessageType`).
    :param payload: The already encoded payload.
    :param source: Client identifier; replies are unicast back when it is not 0 or 1.
    :param sequence: Wrap-around sequence number (0-255) used to match replies.
    :param target: 8-byte device target; all zeroes addresses every device (tagged).
    :param res_required: Ask the device to reply with a State message.
    :param ack_required: Ask the device to reply with an Acknowledgement.
    """
    tagged = target == BROADCAST_TARGET
    protocol = PROTOCOL_NUMBER | _ADDRESSABLE | (_TAGGED if tagged else 0)
    flags = (_FLAG_RES_REQUIRED if res_required else 0) | (
        _FLAG_ACK_REQUIRED if ack_required else 0
    )
    header = _HEADER.pack(
        HEADER_SIZE + len(payload),
        protocol,
        source,
        target,
        b"\x00" * 6,
        flags,
        sequence & 0xFF,
        0,
        msg_type,
        0,
    )
    return header + payload


def decode_header(data: bytes) -> Header:
    """
    Decode the header of a received packet.

    :param data: The raw datagram.
    """
    if len(data) < HEADER_SIZE:
        msg = f"LIFX packet too short ({len(data)} bytes)"
        raise ValueError(msg)
    size, protocol, source, target, _res, flags, sequence, _r2, msg_type, _r3 = _HEADER.unpack_from(
        data
    )
    if protocol & 0x0FFF != PROTOCOL_NUMBER:
        msg = f"Not a LIFX packet (protocol {protocol & 0x0FFF})"
        raise ValueError(msg)
    return Header(
        size=size,
        tagged=bool(protocol & _TAGGED),
        source=source,
        target=target,
        res_required=bool(flags & _FLAG_RES_REQUIRED),
        ack_required=bool(flags & _FLAG_ACK_REQUIRED),
        sequence=sequence,
        type=msg_type,
    )


# -- Payload encoders --


def encode_hsbk(color: HSBK) -> bytes:
    """Encode a single HSBK colour."""
    return _HSBK.pack(
        color.hue & 0xFFFF,
        color.saturation & 0xFFFF,
        color.brightness & 0xFFFF,
        color.kelvin & 0xFFFF,
    )


def light_set_color(color: HSBK, duration_ms: int) -> bytes:
    """Payload for LightSetColor (102)."""
    return b"\x00" + encode_hsbk(color) + struct.pack("<I", max(0, duration_ms))


def light_set_power(level: int, duration_ms: int) -> bytes:
    """Payload for LightSetPower (117); ``level`` is 0 (off) or 65535 (on)."""
    return struct.pack("<HI", level & 0xFFFF, max(0, duration_ms))


def set_color_zones(
    start_index: int, end_index: int, color: HSBK, duration_ms: int, apply: ZoneApply
) -> bytes:
    """Payload for the legacy SetColorZones (501)."""
    return (
        struct.pack("<BB", start_index & 0xFF, end_index & 0xFF)
        + encode_hsbk(color)
        + struct.pack("<IB", max(0, duration_ms), int(apply))
    )


def get_color_zones(start_index: int = 0, end_index: int = 255) -> bytes:
    """Payload for the legacy GetColorZones (502)."""
    return struct.pack("<BB", start_index & 0xFF, end_index & 0xFF)


def set_extended_color_zones(
    colors: list[HSBK], duration_ms: int, zone_index: int = 0, apply: ZoneApply = ZoneApply.APPLY
) -> bytes:
    """
    Payload for SetExtendedColorZones (510).

    :param colors: Up to 82 zone colours starting at ``zone_index``.
    :param duration_ms: Transition time.
    :param zone_index: First zone the colours apply to.
    :param apply: Apply mode.
    """
    count = min(len(colors), EXTENDED_ZONES_PER_MESSAGE)
    padded = list(colors[:count]) + [HSBK()] * (EXTENDED_ZONES_PER_MESSAGE - count)
    return struct.pack("<IBHB", max(0, duration_ms), int(apply), zone_index & 0xFFFF, count) + (
        b"".join(encode_hsbk(c) for c in padded)
    )


# -- Payload decoders --


def decode_hsbk(data: bytes, offset: int = 0) -> HSBK:
    """Decode a single HSBK colour at ``offset``."""
    hue, sat, bri, kelvin = _HSBK.unpack_from(data, offset)
    return HSBK(hue, sat, bri, kelvin)


def decode_state_service(payload: bytes) -> tuple[int, int]:
    """Decode StateService (3) into ``(service, port)``."""
    service, port = struct.unpack_from("<BI", payload)
    return service, port


def decode_label(raw: bytes) -> str:
    """Decode a NUL-padded 32-byte UTF-8 label."""
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


def decode_state_label(payload: bytes) -> str:
    """Decode StateLabel (25)."""
    return decode_label(payload[:32])


def decode_state_version(payload: bytes) -> tuple[int, int]:
    """Decode StateVersion (33) into ``(vendor, product)``."""
    vendor, product, _reserved = struct.unpack_from("<III", payload)
    return vendor, product


def decode_state_group(payload: bytes) -> tuple[str, str]:
    """Decode StateGroup (53) into ``(group_id_hex, label)``."""
    group_id, label, _updated_at = struct.unpack_from("<16s32sQ", payload)
    return group_id.hex(), decode_label(label)


def decode_light_state(payload: bytes) -> tuple[HSBK, int, str]:
    """Decode LightState (107) into ``(color, power, label)``."""
    color = decode_hsbk(payload, 0)
    _reserved, power = struct.unpack_from("<hH", payload, 8)
    label = decode_label(payload[12:44])
    return color, power, label


def decode_state_multi_zone(payload: bytes) -> tuple[int, int, list[HSBK]]:
    """Decode StateMultiZone (506) into ``(zone_count, index, colors)``."""
    count, index = struct.unpack_from("<BB", payload)
    colors = [decode_hsbk(payload, 2 + i * 8) for i in range(LEGACY_ZONES_PER_MESSAGE)]
    return count, index, colors


def decode_state_zone(payload: bytes) -> tuple[int, int, HSBK]:
    """Decode StateZone (503) into ``(zone_count, index, color)``."""
    count, index = struct.unpack_from("<BB", payload)
    return count, index, decode_hsbk(payload, 2)


def decode_state_extended_color_zones(payload: bytes) -> tuple[int, int, list[HSBK]]:
    """Decode StateExtendedColorZones (512) into ``(zone_count, index, colors)``."""
    count, index, colors_count = struct.unpack_from("<HHB", payload)
    colors_count = min(colors_count, EXTENDED_ZONES_PER_MESSAGE)
    colors = [decode_hsbk(payload, 5 + i * 8) for i in range(colors_count)]
    return count, index, colors


# -- Colour conversion --


def rgb16_to_hsbk(red: int, green: int, blue: int, kelvin: int = DEFAULT_KELVIN) -> HSBK:
    """
    Convert 16-bit RGB to a LIFX HSBK colour.

    Brightness carries the RGB value (max channel), so a dimmed RGB colour becomes a
    dimmed LIFX colour with the same hue and saturation.

    :param red: Red channel (0-65535).
    :param green: Green channel (0-65535).
    :param blue: Blue channel (0-65535).
    :param kelvin: White point used for low-saturation colours.
    """
    r = max(0, min(65535, red)) / 65535.0
    g = max(0, min(65535, green)) / 65535.0
    b = max(0, min(65535, blue)) / 65535.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return HSBK(
        hue=round(h * 65535) & 0xFFFF,
        saturation=round(s * 65535),
        brightness=round(v * 65535),
        kelvin=kelvin,
    )


__all__ = [
    "BROADCAST_TARGET",
    "Header",
    "MessageType",
    "ZoneApply",
    "decode_header",
    "encode_message",
    "rgb16_to_hsbk",
]
