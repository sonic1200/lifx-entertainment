"""Build entertainment areas (and their light channels) from discovered devices."""

from __future__ import annotations

import hashlib
from enum import StrEnum

from .models import EntertainmentArea, LifxDevice, LightChannel

# A multizone strip is split into at most this many channels, so the analyzer's
# per-channel spectrum bands stay musically meaningful on long strips.
DEFAULT_MAX_SEGMENTS = 8


class Grouping(StrEnum):
    """How devices are combined into entertainment areas."""

    # One area per LIFX group (the rooms configured in the LIFX app).
    GROUP = "group"
    # One area containing every device.
    ALL = "all"
    # One area per device.
    LIGHT = "light"


def build_areas(
    devices: list[LifxDevice],
    grouping: Grouping | str = Grouping.GROUP,
    *,
    all_name: str = "All lights",
    max_segments: int = DEFAULT_MAX_SEGMENTS,
) -> list[EntertainmentArea]:
    """Combine devices into entertainment areas."""
    grouping = Grouping(grouping)
    ordered = sorted(devices, key=lambda d: (d.label.lower(), d.serial))
    buckets: dict[str, tuple[str, list[LifxDevice]]] = {}
    for device in ordered:
        if grouping == Grouping.ALL:
            key, name = "all", all_name
        elif grouping == Grouping.LIGHT:
            key, name = f"light-{device.serial}", device.label or device.serial
        else:
            group = device.group_id or "nogroup"
            key, name = f"group-{group}", device.group_label or all_name
        buckets.setdefault(key, (name, []))[1].append(device)
    areas = [
        EntertainmentArea(
            id=key,
            name=name,
            devices=members,
            channels=build_channels(members, max_segments=max_segments),
        )
        for key, (name, members) in buckets.items()
    ]
    return sorted(areas, key=lambda a: a.name.lower())


def build_channels(
    devices: list[LifxDevice], *, max_segments: int = DEFAULT_MAX_SEGMENTS
) -> list[LightChannel]:
    """
    Create the light channels for a set of devices.

    Channels are laid out left to right along the x axis in device order, which gives the
    analyzer a spatial axis to spread its colour gradient over.
    """
    specs: list[tuple[LifxDevice, int, int, str]] = []
    for device in devices:
        name = device.label or device.serial
        if not device.is_multizone:
            specs.append((device, 0, 1, name))
            continue
        segments = max(1, min(max_segments, device.zone_count))
        for segment in range(segments):
            start = segment * device.zone_count // segments
            end = (segment + 1) * device.zone_count // segments
            specs.append((device, start, end, f"{name} #{segment + 1}"))
    count = len(specs)
    channels: list[LightChannel] = []
    for index, (device, start, end, name) in enumerate(specs):
        x = 0.0 if count == 1 else -1.0 + 2.0 * index / (count - 1)
        channels.append(
            LightChannel(
                channel_id=index,
                service_id=device.serial,
                name=name,
                position=(x, 0.0, 0.0),
                zone_start=start,
                zone_end=end,
            )
        )
    return channels


def area_client_id(area_id: str, namespace: str = "") -> str:
    """Return a short stable identifier for an area (e.g. for a player id)."""
    return hashlib.sha1(f"{namespace}:{area_id}".encode(), usedforsecurity=False).hexdigest()[:16]
