"""Discover LIFX devices on the LAN via UDP broadcast."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from .api import LifxLanAPI
from .constants import DEFAULT_BROADCAST, LIFX_PORT, SERVICE_UDP, MessageType
from .models import LifxDevice
from .protocol import Header, decode_state_service
from .transport import LifxTransport

LOGGER = logging.getLogger(__name__)

DEFAULT_DISCOVERY_TIMEOUT_S = 3.0
# GetService is re-broadcast a few times during the window: UDP broadcasts get lost.
_BROADCAST_INTERVAL_S = 0.6


async def discover_devices(
    transport: LifxTransport | None = None,
    *,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT_S,
    broadcast: str = DEFAULT_BROADCAST,
    hosts: list[str] | None = None,
    details: bool = True,
    port: int = LIFX_PORT,
) -> list[LifxDevice]:
    """
    Find LIFX devices on the network.

    :param transport: Opened transport to use; a temporary one is created when omitted.
    :param timeout: Seconds to listen for replies.
    :param broadcast: Broadcast address to send GetService to (e.g. ``192.168.1.255``).
    :param hosts: Extra device IPs to probe directly (for networks that drop broadcasts).
    :param details: Also fetch label, group, product and zone layout for every device.
    :param port: UDP port the devices listen on.
    :return: The discovered devices, sorted by label.
    """
    own_transport = transport is None
    if transport is None:
        transport = LifxTransport()
        await transport.open()
    found: dict[str, LifxDevice] = {}

    def _on_packet(header: Header, payload: bytes, addr: tuple[str, int]) -> None:
        if header.type != MessageType.STATE_SERVICE:
            return
        service, port = decode_state_service(payload)
        if service != SERVICE_UDP:
            return
        serial = header.serial
        if not serial or serial == "000000000000":
            return
        if serial in found:
            found[serial].host = addr[0]
            found[serial].port = port
            return
        found[serial] = LifxDevice(serial=serial, host=addr[0], port=port)

    remove = transport.add_listener(_on_packet)
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        targets = [broadcast, *(hosts or [])]
        while loop.time() < deadline:
            for host in targets:
                with suppress(OSError):
                    transport.send(host, MessageType.GET_SERVICE, port=port)
            await asyncio.sleep(min(_BROADCAST_INTERVAL_S, max(0.0, deadline - loop.time())))
    finally:
        remove()

    devices = list(found.values())
    try:
        if details and devices:
            api = LifxLanAPI(transport)
            await asyncio.gather(*(refresh_device(api, device) for device in devices))
    finally:
        if own_transport:
            transport.close()
    LOGGER.debug("Discovered %d LIFX device(s)", len(devices))
    return sorted(devices, key=lambda d: (d.label.lower(), d.serial))


async def refresh_device(api: LifxLanAPI, device: LifxDevice) -> bool:
    """
    Fetch label, group, product and zone layout for a device (best effort).

    :param api: API bound to an opened transport.
    :param device: The device to update in place.
    :return: True when the device answered.
    """
    try:
        _color, _power, device.label = await api.get_light_state(device)
    except (TimeoutError, NotImplementedError):
        LOGGER.debug("LIFX device %s at %s did not answer", device.serial, device.host)
        return False
    with suppress(TimeoutError, NotImplementedError):
        device.group_id, device.group_label = await api.get_group(device)
    with suppress(TimeoutError, NotImplementedError):
        device.product_id = await api.get_product_id(device)
    device.zone_support, device.zone_count = await api.probe_zones(device)
    return True
