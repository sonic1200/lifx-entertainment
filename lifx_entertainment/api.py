"""High-level request helpers for individual LIFX devices."""

from __future__ import annotations

import math
from contextlib import suppress

from . import protocol
from .constants import (
    EXTENDED_ZONES_PER_MESSAGE,
    LEGACY_ZONES_PER_MESSAGE,
    MessageType,
    ZoneApply,
)
from .models import HSBK, DeviceSnapshot, LifxDevice, ZoneSupport
from .transport import LifxTransport


class LifxLanAPI:
    """Typed request/response wrapper around a :class:`LifxTransport`."""

    def __init__(self, transport: LifxTransport) -> None:
        """Initialize the API."""
        self.transport = transport

    async def get_label(self, device: LifxDevice) -> str:
        """Return the device label as set in the LIFX app."""
        replies = await self._request(device, MessageType.GET_LABEL, (MessageType.STATE_LABEL,))
        return protocol.decode_state_label(replies[0][1])

    async def get_group(self, device: LifxDevice) -> tuple[str, str]:
        """Return the device's ``(group_id, group_label)`` (its room in the LIFX app)."""
        replies = await self._request(device, MessageType.GET_GROUP, (MessageType.STATE_GROUP,))
        return protocol.decode_state_group(replies[0][1])

    async def get_product_id(self, device: LifxDevice) -> int:
        """Return the LIFX product id."""
        replies = await self._request(device, MessageType.GET_VERSION, (MessageType.STATE_VERSION,))
        return protocol.decode_state_version(replies[0][1])[1]

    async def get_light_state(self, device: LifxDevice) -> tuple[HSBK, int, str]:
        """Return the device's ``(color, power, label)``."""
        replies = await self._request(device, MessageType.LIGHT_GET, (MessageType.LIGHT_STATE,))
        return protocol.decode_light_state(replies[0][1])

    async def probe_zones(self, device: LifxDevice) -> tuple[ZoneSupport, int]:
        """
        Detect how (and how many) colour zones the device exposes.

        Non-multizone devices answer zone requests with StateUnhandled (or not at all),
        which maps to ``(ZoneSupport.NONE, 1)``.
        """
        with suppress(TimeoutError, NotImplementedError):
            replies = await self._request(
                device,
                MessageType.GET_EXTENDED_COLOR_ZONES,
                (MessageType.STATE_EXTENDED_COLOR_ZONES,),
                retries=2,
            )
            count, _index, _colors = protocol.decode_state_extended_color_zones(replies[0][1])
            if count > 0:
                return ZoneSupport.EXTENDED, count
        with suppress(TimeoutError, NotImplementedError):
            replies = await self._request(
                device,
                MessageType.GET_COLOR_ZONES,
                (MessageType.STATE_MULTI_ZONE, MessageType.STATE_ZONE),
                protocol.get_color_zones(0, 0),
                retries=2,
            )
            count = replies[0][1][0]
            if count > 0:
                return ZoneSupport.LEGACY, count
        return ZoneSupport.NONE, 1

    async def get_zone_colors(self, device: LifxDevice) -> list[HSBK]:
        """Return the colour of every zone of a multizone device."""
        if device.zone_support == ZoneSupport.EXTENDED:
            messages = math.ceil(device.zone_count / EXTENDED_ZONES_PER_MESSAGE)
            replies = await self._request(
                device,
                MessageType.GET_EXTENDED_COLOR_ZONES,
                (MessageType.STATE_EXTENDED_COLOR_ZONES,),
                expected=messages,
            )
            zones: dict[int, HSBK] = {}
            for _header, payload in replies:
                _count, index, colors = protocol.decode_state_extended_color_zones(payload)
                for offset, color in enumerate(colors):
                    zones[index + offset] = color
        elif device.zone_support == ZoneSupport.LEGACY:
            messages = math.ceil(device.zone_count / LEGACY_ZONES_PER_MESSAGE)
            replies = await self._request(
                device,
                MessageType.GET_COLOR_ZONES,
                (MessageType.STATE_MULTI_ZONE, MessageType.STATE_ZONE),
                protocol.get_color_zones(0, 255),
                expected=messages,
            )
            zones = {}
            for header, payload in replies:
                if header.type == MessageType.STATE_ZONE:
                    _count, index, color = protocol.decode_state_zone(payload)
                    zones[index] = color
                    continue
                _count, index, colors = protocol.decode_state_multi_zone(payload)
                for offset, color in enumerate(colors):
                    zones[index + offset] = color
        else:
            return []
        fallback = next(iter(zones.values()), HSBK())
        return [zones.get(i, fallback) for i in range(device.zone_count)]

    async def snapshot(self, device: LifxDevice) -> DeviceSnapshot:
        """Capture the device's power, colour and (multizone) zone colours."""
        color, power, _label = await self.get_light_state(device)
        zones: tuple[HSBK, ...] = ()
        if device.is_multizone:
            with suppress(TimeoutError, NotImplementedError):
                zones = tuple(await self.get_zone_colors(device))
        return DeviceSnapshot(power=power, color=color, zones=zones)

    async def set_power(self, device: LifxDevice, on: bool, duration_ms: int = 0) -> None:
        """Switch the device on or off and wait for the acknowledgement."""
        await self._request(
            device,
            MessageType.LIGHT_SET_POWER,
            (MessageType.ACKNOWLEDGEMENT,),
            protocol.light_set_power(65535 if on else 0, duration_ms),
        )

    async def set_color(self, device: LifxDevice, color: HSBK, duration_ms: int = 0) -> None:
        """Set the whole device to one colour and wait for the acknowledgement."""
        await self._request(
            device,
            MessageType.LIGHT_SET_COLOR,
            (MessageType.ACKNOWLEDGEMENT,),
            protocol.light_set_color(color, duration_ms),
        )

    async def set_zone_colors(
        self, device: LifxDevice, colors: list[HSBK], duration_ms: int = 0
    ) -> None:
        """Set every zone of a multizone device and wait for the acknowledgement(s)."""
        for message in zone_messages(device, colors, duration_ms):
            msg_type, payload = message
            await self._request(device, msg_type, (MessageType.ACKNOWLEDGEMENT,), payload)

    async def restore(
        self, device: LifxDevice, snapshot: DeviceSnapshot, duration_ms: int = 0
    ) -> None:
        """Restore a state captured by :meth:`snapshot`."""
        if snapshot.zones and device.is_multizone:
            await self.set_zone_colors(device, list(snapshot.zones), duration_ms)
        else:
            await self.set_color(device, snapshot.color, duration_ms)
        await self.set_power(device, snapshot.power > 0, duration_ms)

    async def _request(
        self,
        device: LifxDevice,
        msg_type: int,
        response_types: tuple[int, ...],
        payload: bytes = b"",
        *,
        expected: int = 1,
        retries: int = 3,
    ) -> list[tuple[protocol.Header, bytes]]:
        return await self.transport.request(
            device.host,
            device.target,
            msg_type,
            payload,
            response_types=response_types,
            port=device.port,
            expected=expected,
            retries=retries,
        )


def zone_messages(
    device: LifxDevice, colors: list[HSBK], duration_ms: int
) -> list[tuple[int, bytes]]:
    """
    Build the ``(msg_type, payload)`` messages that set every zone of a multizone device.

    Extended devices take up to 82 zones per message; legacy devices take one message per
    run of identical colours, applying everything with the last one.
    """
    if not colors:
        return []
    if device.zone_support == ZoneSupport.EXTENDED:
        chunks = range(0, len(colors), EXTENDED_ZONES_PER_MESSAGE)
        return [
            (
                MessageType.SET_EXTENDED_COLOR_ZONES,
                protocol.set_extended_color_zones(
                    colors[start : start + EXTENDED_ZONES_PER_MESSAGE],
                    duration_ms,
                    zone_index=start,
                    apply=ZoneApply.APPLY
                    if start + EXTENDED_ZONES_PER_MESSAGE >= len(colors)
                    else ZoneApply.NO_APPLY,
                ),
            )
            for start in chunks
        ]
    runs: list[tuple[int, int, HSBK]] = []
    for index, color in enumerate(colors):
        if runs and runs[-1][2] == color:
            runs[-1] = (runs[-1][0], index, color)
        else:
            runs.append((index, index, color))
    return [
        (
            MessageType.SET_COLOR_ZONES,
            protocol.set_color_zones(
                start,
                end,
                color,
                duration_ms,
                ZoneApply.APPLY if i == len(runs) - 1 else ZoneApply.NO_APPLY,
            ),
        )
        for i, (start, end, color) in enumerate(runs)
    ]
