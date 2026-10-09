"""High-level async session that streams colour frames to an entertainment area."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from .api import LifxLanAPI, zone_messages
from .constants import DEFAULT_KELVIN, MAX_MESSAGES_PER_SECOND, MessageType
from .models import HSBK, DeviceSnapshot, EntertainmentArea, LifxDevice, LightColorCommand
from .protocol import light_set_color, rgb16_to_hsbk

LOGGER = logging.getLogger(__name__)

DEFAULT_TRANSITION_MS = 50
DEFAULT_RESTORE_DURATION_MS = 1000
# Unchanged frames are suppressed, but re-sent this often so a dropped UDP packet
# never leaves a light stuck on a stale colour.
_KEEPALIVE_S = 1.0


class EntertainmentSession:
    """
    Asyncio facade that streams colours to every device of an entertainment area.

    On :meth:`start` the current state of each device is captured (and lights that are
    off are switched on); frames pushed with :meth:`send` are converted to HSBK and sent
    fire-and-forget over UDP; :meth:`stop` restores the captured state. LIFX devices need
    no bridge, pairing or stream handshake, so a session is cheap to start and stop.
    """

    def __init__(
        self,
        api: LifxLanAPI,
        area: EntertainmentArea,
        *,
        transition_ms: int = DEFAULT_TRANSITION_MS,
        power_on: bool = True,
        restore: bool = True,
        restore_duration_ms: int = DEFAULT_RESTORE_DURATION_MS,
        kelvin: int = DEFAULT_KELVIN,
        max_rate_hz: float = MAX_MESSAGES_PER_SECOND,
    ) -> None:
        """
        Initialize the session (no network I/O until :meth:`start`).

        :param api: API bound to an opened transport.
        :param area: The area to stream to.
        :param transition_ms: Fade time of each frame; smooths over frame jitter.
        :param power_on: Switch on devices that are off when the session starts.
        :param restore: Restore each device's previous state when the session stops.
        :param restore_duration_ms: Fade time back to the previous state.
        :param kelvin: White point for low-saturation colours.
        :param max_rate_hz: Maximum messages per second sent to a single device.
        """
        self._api = api
        self.area = area
        self.transition_ms = transition_ms
        self._power_on = power_on
        self._restore = restore
        self._restore_duration_ms = restore_duration_ms
        self._kelvin = kelvin
        self._min_interval = 1.0 / max_rate_hz if max_rate_hz > 0 else 0.0
        self._channels = {ch.channel_id: ch for ch in area.channels}
        self._devices = {d.serial: d for d in area.devices}
        self._snapshots: dict[str, DeviceSnapshot] = {}
        self._last_payload: dict[str, tuple[bytes, ...]] = {}
        self._last_sent: dict[str, float] = {}
        self._next_allowed: dict[str, float] = {}
        self._zone_frames: dict[str, list[HSBK]] = {}
        self._streaming = False
        self._lock = asyncio.Lock()

    @property
    def is_streaming(self) -> bool:
        """Return True while the session is active."""
        return self._streaming

    async def start(self) -> None:
        """Capture every device's state, switch lights on and begin accepting frames."""
        async with self._lock:
            if self._streaming:
                return
            results = await asyncio.gather(
                *(self._prepare_device(d) for d in self._devices.values()),
                return_exceptions=True,
            )
            reachable = 0
            for device, result in zip(self._devices.values(), results, strict=True):
                if isinstance(result, BaseException):
                    LOGGER.warning(
                        "LIFX device %s (%s) not ready: %s", device.label, device.host, result
                    )
                    continue
                reachable += 1
            if self._devices and reachable == 0:
                msg = f"No LIFX device of area '{self.area.name}' is reachable"
                raise ConnectionError(msg)
            self._last_payload.clear()
            self._last_sent.clear()
            self._next_allowed.clear()
            self._zone_frames = {
                d.serial: [HSBK(kelvin=self._kelvin)] * d.zone_count
                for d in self._devices.values()
                if d.is_multizone
            }
            self._streaming = True
            LOGGER.info(
                "LIFX session started for area '%s' (%d/%d devices)",
                self.area.name,
                reachable,
                len(self._devices),
            )

    def send(self, commands: list[LightColorCommand]) -> None:
        """
        Push a frame of channel colours to the devices.

        Non-blocking and safe to call from the event loop; a no-op when not streaming.

        :param commands: One color command per channel to update this frame.
        """
        if not self._streaming or not self._api.transport.is_open:
            return
        per_device: dict[str, list[tuple[int, int, HSBK]]] = {}
        for command in commands:
            channel = self._channels.get(command.channel_id)
            if channel is None:
                continue
            color = rgb16_to_hsbk(command.red, command.green, command.blue, self._kelvin)
            per_device.setdefault(channel.service_id, []).append(
                (channel.zone_start, channel.zone_end, color)
            )
        now = time.monotonic()
        for serial, updates in per_device.items():
            device = self._devices.get(serial)
            if device is None:
                continue
            messages = self._build_messages(device, updates)
            self._send_device(device, messages, now)

    async def stop(self) -> None:
        """Stop streaming and restore the captured device state."""
        async with self._lock:
            # A start that failed or was cancelled halfway may already have switched
            # lights on, so restore whatever was captured even if never streaming.
            if not self._streaming and not self._snapshots:
                return
            self._streaming = False
            if self._restore and self._snapshots:
                await asyncio.gather(
                    *(
                        self._restore_device(self._devices[serial], snapshot)
                        for serial, snapshot in self._snapshots.items()
                        if serial in self._devices
                    ),
                    return_exceptions=True,
                )
            self._snapshots.clear()
            LOGGER.info("LIFX session stopped for area '%s'", self.area.name)

    async def aclose(self) -> None:
        """Stop streaming (alias kept for API parity with the Hue library)."""
        await self.stop()

    async def _prepare_device(self, device: LifxDevice) -> None:
        # Keep the first capture across start retries: by then this session may already
        # have switched the light on, which must not become the state to restore.
        snapshot = self._snapshots.get(device.serial)
        if snapshot is None:
            snapshot = await self._api.snapshot(device)
            self._snapshots[device.serial] = snapshot
        if snapshot.power == 0 and self._power_on:
            # Go dark before powering up so the light doesn't flash its old colour.
            await self._api.set_color(device, HSBK(kelvin=self._kelvin), 0)
            await self._api.set_power(device, on=True)

    async def _restore_device(self, device: LifxDevice, snapshot: DeviceSnapshot) -> None:
        try:
            await self._api.restore(device, snapshot, self._restore_duration_ms)
        except Exception as err:
            LOGGER.warning("Failed to restore LIFX device %s: %s", device.label, err)

    def _build_messages(
        self, device: LifxDevice, updates: list[tuple[int, int, HSBK]]
    ) -> list[tuple[int, bytes]]:
        if not device.is_multizone:
            # A plain bulb has a single channel; if several map to it, average them.
            color = updates[0][2] if len(updates) == 1 else _average([u[2] for u in updates])
            return [(MessageType.LIGHT_SET_COLOR, light_set_color(color, self.transition_ms))]
        zones = self._zone_frames.setdefault(
            device.serial, [HSBK(kelvin=self._kelvin)] * device.zone_count
        )
        for start, end, color in updates:
            for index in range(max(0, start), min(device.zone_count, end)):
                zones[index] = color
        return zone_messages(device, zones, self.transition_ms)

    def _send_device(
        self, device: LifxDevice, messages: list[tuple[int, bytes]], now: float
    ) -> None:
        if not messages:
            return
        payloads = tuple(payload for _type, payload in messages)
        unchanged = self._last_payload.get(device.serial) == payloads
        if unchanged and now - self._last_sent.get(device.serial, 0.0) < _KEEPALIVE_S:
            return
        if now < self._next_allowed.get(device.serial, 0.0):
            return
        for msg_type, payload in messages:
            with suppress(OSError, RuntimeError):
                self._api.transport.send(
                    device.host, msg_type, payload, target=device.target, port=device.port
                )
        self._last_payload[device.serial] = payloads
        self._last_sent[device.serial] = now
        # Small tolerance so a render loop running at exactly the device rate isn't
        # throttled by scheduling jitter.
        self._next_allowed[device.serial] = now + self._min_interval * len(messages) * 0.9


def _average(colors: list[HSBK]) -> HSBK:
    """Average colours component-wise (only used when several channels share one bulb)."""
    count = len(colors)
    return HSBK(
        hue=sum(c.hue for c in colors) // count,
        saturation=sum(c.saturation for c in colors) // count,
        brightness=sum(c.brightness for c in colors) // count,
        kelvin=colors[0].kelvin,
    )
