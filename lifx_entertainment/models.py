"""Data models for LIFX entertainment streaming."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .constants import DEFAULT_KELVIN, LIFX_PORT


class ZoneSupport(StrEnum):
    """How a device's colour zones are addressed."""

    NONE = "none"
    LEGACY = "legacy"
    EXTENDED = "extended"


@dataclass(frozen=True, slots=True)
class HSBK:
    """A LIFX colour: 16-bit hue, saturation, brightness and a kelvin white point."""

    hue: int = 0
    saturation: int = 0
    brightness: int = 0
    kelvin: int = DEFAULT_KELVIN


@dataclass
class LifxDevice:
    """A LIFX device on the LAN."""

    serial: str
    host: str
    port: int = LIFX_PORT
    label: str = ""
    group_id: str = ""
    group_label: str = ""
    product_id: int = 0
    zone_support: ZoneSupport = ZoneSupport.NONE
    zone_count: int = 1

    @property
    def is_multizone(self) -> bool:
        """Return True when the device has individually addressable zones."""
        return self.zone_support != ZoneSupport.NONE and self.zone_count > 1

    @property
    def target(self) -> bytes:
        """Return the 8-byte frame-address target for this device."""
        return bytes.fromhex(self.serial) + b"\x00\x00"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (for persisting in a config store)."""
        return {
            "serial": self.serial,
            "host": self.host,
            "port": self.port,
            "label": self.label,
            "group_id": self.group_id,
            "group_label": self.group_label,
            "product_id": self.product_id,
            "zone_support": str(self.zone_support),
            "zone_count": self.zone_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifxDevice:
        """
        Deserialize a dict produced by :meth:`to_dict`.

        :param data: The serialized device.
        """
        return cls(
            serial=str(data["serial"]),
            host=str(data["host"]),
            port=int(data.get("port", LIFX_PORT)),
            label=str(data.get("label", "")),
            group_id=str(data.get("group_id", "")),
            group_label=str(data.get("group_label", "")),
            product_id=int(data.get("product_id", 0)),
            zone_support=ZoneSupport(data.get("zone_support", ZoneSupport.NONE)),
            zone_count=int(data.get("zone_count", 1)),
        )


@dataclass
class LightChannel:
    """
    A single light channel of an entertainment area.

    A plain bulb is one channel; a multizone strip is split into several channels, each
    driving a contiguous range of zones ``[zone_start, zone_end)``.
    """

    channel_id: int
    service_id: str
    name: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    zone_start: int = 0
    zone_end: int = 1


@dataclass
class EntertainmentArea:
    """A set of LIFX devices that react to music together."""

    id: str
    name: str
    devices: list[LifxDevice] = field(default_factory=list)
    channels: list[LightChannel] = field(default_factory=list)


@dataclass
class LightColorCommand:
    """A color command for a single light channel (16-bit RGB)."""

    channel_id: int
    red: int = 0  # 0-65535
    green: int = 0  # 0-65535
    blue: int = 0  # 0-65535


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """The state of a device captured before streaming, restored afterwards."""

    power: int
    color: HSBK
    zones: tuple[HSBK, ...] = ()
