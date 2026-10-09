"""Tests for the LIFX packet encoder/decoder and colour conversion."""

from __future__ import annotations

import struct

import pytest

from lifx_entertainment import protocol
from lifx_entertainment.constants import MessageType
from lifx_entertainment.models import HSBK


def test_header_roundtrip():
    target = bytes.fromhex("d073d5012345") + b"\x00\x00"
    packet = protocol.encode_message(
        MessageType.LIGHT_GET, source=1234, sequence=7, target=target, res_required=True
    )
    assert len(packet) == 36
    header = protocol.decode_header(packet)
    assert header.size == 36
    assert header.source == 1234
    assert header.sequence == 7
    assert header.type == MessageType.LIGHT_GET
    assert header.serial == "d073d5012345"
    assert header.res_required
    assert not header.ack_required
    assert not header.tagged


def test_broadcast_is_tagged():
    packet = protocol.encode_message(MessageType.GET_SERVICE, source=5, sequence=1)
    header = protocol.decode_header(packet)
    assert header.tagged
    # protocol 1024 with the addressable and tagged bits, as documented by LIFX
    assert packet[2:4] == bytes.fromhex("0034")


def test_decode_rejects_garbage():
    with pytest.raises(ValueError, match="too short"):
        protocol.decode_header(b"\x00" * 10)
    with pytest.raises(ValueError, match="Not a LIFX packet"):
        protocol.decode_header(b"\x24\x00\x00\x00" + b"\x00" * 32)


def test_set_color_payload():
    payload = protocol.light_set_color(HSBK(1, 2, 3, 4), 50)
    assert len(payload) == 13
    assert protocol.decode_hsbk(payload, 1) == HSBK(1, 2, 3, 4)
    assert struct.unpack_from("<I", payload, 9)[0] == 50


def test_extended_zones_payload():
    colors = [HSBK(i, 5, 5, 3500) for i in range(16)]
    payload = protocol.set_extended_color_zones(colors, 50, zone_index=0)
    assert len(payload) == 8 + 82 * 8
    duration, apply, index, count = struct.unpack_from("<IBHB", payload)
    assert (duration, apply, index, count) == (50, 1, 0, 16)
    assert [protocol.decode_hsbk(payload, 8 + i * 8) for i in range(16)] == colors


def test_state_extended_zones_decode():
    colors = [HSBK(i, 1, 2, 3) for i in range(82)]
    payload = struct.pack("<HHB", 20, 0, 20) + b"".join(protocol.encode_hsbk(c) for c in colors)
    count, index, decoded = protocol.decode_state_extended_color_zones(payload)
    assert (count, index) == (20, 0)
    assert decoded == colors[:20]


def test_light_state_decode():
    label = b"Kitchen".ljust(32, b"\x00")
    payload = (
        protocol.encode_hsbk(HSBK(1, 2, 3, 4)) + struct.pack("<hH", 0, 65535) + label + b"\x00" * 8
    )
    assert protocol.decode_light_state(payload) == (HSBK(1, 2, 3, 4), 65535, "Kitchen")


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((65535, 0, 0), HSBK(0, 65535, 65535, 3500)),
        ((0, 0, 0), HSBK(0, 0, 0, 3500)),
        ((65535, 65535, 65535), HSBK(0, 0, 65535, 3500)),
    ],
)
def test_rgb_to_hsbk(rgb, expected):
    assert protocol.rgb16_to_hsbk(*rgb) == expected


def test_rgb_to_hsbk_keeps_hue_when_dimmed():
    full = protocol.rgb16_to_hsbk(0, 65535, 0)
    dim = protocol.rgb16_to_hsbk(0, 32767, 0)
    assert dim.hue == full.hue
    assert dim.saturation == full.saturation
    assert dim.brightness == pytest.approx(32767, abs=1)
