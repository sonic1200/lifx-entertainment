"""End-to-end tests against fake LIFX devices on localhost."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from lifx_entertainment import (
    EntertainmentSession,
    LifxDevice,
    LifxLanAPI,
    LifxTransport,
    LightColorCommand,
    ZoneSupport,
    build_areas,
    discover_devices,
)
from lifx_entertainment.constants import MessageType

from .fake_device import FakeLifxDevice


@pytest.fixture
async def transport() -> AsyncIterator[LifxTransport]:
    t = LifxTransport()
    await t.open(("127.0.0.1", 0))
    yield t
    t.close()


@pytest.fixture
async def bulb() -> AsyncIterator[FakeLifxDevice]:
    device = FakeLifxDevice("d073d5aaaaaa", "Bulb", power=0)
    await device.start()
    yield device
    device.close()


@pytest.fixture
async def strip() -> AsyncIterator[FakeLifxDevice]:
    device = FakeLifxDevice("d073d5bbbbbb", "Strip", zones=16)
    await device.start()
    yield device
    device.close()


def _device(fake: FakeLifxDevice) -> LifxDevice:
    return LifxDevice(fake.serial, "127.0.0.1", port=fake.port, label=fake.label)


def _red_frame(session: EntertainmentSession, red: int = 65535) -> list[LightColorCommand]:
    return [LightColorCommand(c.channel_id, red=red) for c in session.area.channels]


async def test_discovery_fetches_details(transport, strip):
    devices = await discover_devices(transport, timeout=0.3, broadcast="127.0.0.1", port=strip.port)
    assert len(devices) == 1
    device = devices[0]
    assert device.serial == strip.serial
    assert device.label == "Strip"
    assert device.group_label == "Living room"
    assert device.product_id == 32
    assert device.zone_support == ZoneSupport.EXTENDED
    assert device.zone_count == 16


async def test_discovery_plain_bulb(transport, bulb):
    devices = await discover_devices(transport, timeout=0.3, broadcast="127.0.0.1", port=bulb.port)
    assert devices[0].zone_support == ZoneSupport.NONE
    assert not devices[0].is_multizone


async def test_request_timeout(transport):
    api = LifxLanAPI(transport)
    ghost = LifxDevice("d073d5cccccc", "127.0.0.1", port=9)
    async with asyncio.timeout(5):
        with pytest.raises(TimeoutError):
            await api.get_label(ghost)


async def test_session_lifecycle(transport, bulb, strip):
    api = LifxLanAPI(transport)
    bulb_dev, strip_dev = _device(bulb), _device(strip)
    strip_dev.zone_support, strip_dev.zone_count = await api.probe_zones(strip_dev)
    original_strip = list(strip.zones)
    original_bulb = bulb.color
    area = build_areas([bulb_dev, strip_dev], "all")[0]
    session = EntertainmentSession(api, area, transition_ms=40, restore_duration_ms=0)

    await session.start()
    assert session.is_streaming
    # the bulb was off: it is darkened, then switched on
    assert bulb.power == 65535
    assert bulb.color.brightness == 0

    session.send(_red_frame(session))
    await asyncio.sleep(0.1)
    assert bulb.color.saturation == 65535
    assert bulb.color.brightness == 65535
    assert all(z.brightness == 65535 and z.hue == 0 for z in strip.zones)
    # streamed frames are fire-and-forget
    assert bulb.of_type(MessageType.LIGHT_SET_COLOR)[-1][0].ack_required is False

    # identical frames are suppressed (until the keepalive)
    count = len(strip.of_type(MessageType.SET_EXTENDED_COLOR_ZONES))
    await asyncio.sleep(0.06)
    session.send(_red_frame(session))
    await asyncio.sleep(0.05)
    assert len(strip.of_type(MessageType.SET_EXTENDED_COLOR_ZONES)) == count

    await session.stop()
    assert not session.is_streaming
    assert bulb.power == 0
    assert bulb.color == original_bulb
    assert strip.zones == original_strip


async def test_per_segment_colors(transport, strip):
    api = LifxLanAPI(transport)
    dev = _device(strip)
    dev.zone_support, dev.zone_count = ZoneSupport.EXTENDED, 16
    area = build_areas([dev], "all", max_segments=2)[0]
    session = EntertainmentSession(api, area, power_on=False, restore=False)
    await session.start()
    session.send([LightColorCommand(0, red=65535), LightColorCommand(1, blue=65535)])
    await asyncio.sleep(0.1)
    assert strip.zones[0] == strip.zones[7]
    assert strip.zones[8] == strip.zones[15]
    assert strip.zones[0] != strip.zones[8]
    await session.stop()


async def test_rate_limit(transport, bulb):
    api = LifxLanAPI(transport)
    area = build_areas([_device(bulb)], "all")[0]
    session = EntertainmentSession(api, area, power_on=False, restore=False, max_rate_hz=5)
    await session.start()
    for i in range(10):
        session.send(_red_frame(session, red=1000 * (i + 1)))
    await asyncio.sleep(0.05)
    assert len(bulb.of_type(MessageType.LIGHT_SET_COLOR)) == 1
    await session.stop()


async def test_unreachable_area_fails_start(transport):
    api = LifxLanAPI(transport)
    ghost = LifxDevice("d073d5dddddd", "127.0.0.1", port=9)
    area = build_areas([ghost], "all")[0]
    session = EntertainmentSession(api, area)
    with pytest.raises(ConnectionError):
        await session.start()
    assert not session.is_streaming


async def test_start_retry_keeps_original_snapshot(transport, bulb):
    api = LifxLanAPI(transport)
    area = build_areas([_device(bulb)], "all")[0]
    session = EntertainmentSession(api, area, restore_duration_ms=0)
    # a first attempt that switched the light on before failing
    await session._prepare_device(area.devices[0])
    assert bulb.power == 65535
    await session.start()
    await session.stop()
    assert bulb.power == 0


async def test_cancelled_start_still_restores(transport, bulb):
    api = LifxLanAPI(transport)
    area = build_areas([_device(bulb)], "all")[0]
    session = EntertainmentSession(api, area, restore_duration_ms=0)
    await session._prepare_device(area.devices[0])
    assert not session.is_streaming
    await session.stop()
    assert bulb.power == 0


async def test_unreachable_probe_keeps_socket_alive(transport, bulb):
    # Windows turns an ICMP "port unreachable" into a reset that used to stop receiving.
    for _ in range(3):
        transport.send("127.0.0.1", MessageType.GET_SERVICE, port=9)
    await asyncio.sleep(0.1)
    assert await LifxLanAPI(transport).get_label(_device(bulb)) == "Bulb"
