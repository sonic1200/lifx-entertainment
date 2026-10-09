"""Tests for grouping devices into areas and channels."""

from __future__ import annotations

from lifx_entertainment import Grouping, LifxDevice, ZoneSupport, area_client_id, build_areas


def _devices() -> list[LifxDevice]:
    return [
        LifxDevice(
            "d073d5000001", "1.1.1.1", label="Globe B", group_id="aa", group_label="Kitchen"
        ),
        LifxDevice(
            "d073d5000002", "1.1.1.2", label="Globe A", group_id="aa", group_label="Kitchen"
        ),
        LifxDevice(
            "d073d5000003",
            "1.1.1.3",
            label="Strip",
            group_id="bb",
            group_label="Living",
            zone_support=ZoneSupport.EXTENDED,
            zone_count=16,
        ),
    ]


def test_group_areas():
    areas = build_areas(_devices(), Grouping.GROUP)
    assert [a.name for a in areas] == ["Kitchen", "Living"]
    kitchen = areas[0]
    assert [c.name for c in kitchen.channels] == ["Globe A", "Globe B"]
    assert [c.position[0] for c in kitchen.channels] == [-1.0, 1.0]


def test_multizone_is_split_into_segments():
    living = build_areas(_devices(), "group")[1]
    assert len(living.channels) == 8
    assert [(c.zone_start, c.zone_end) for c in living.channels][:2] == [(0, 2), (2, 4)]
    assert living.channels[-1].zone_end == 16
    assert {c.service_id for c in living.channels} == {"d073d5000003"}


def test_all_and_light_groupings():
    assert len(build_areas(_devices(), Grouping.ALL)) == 1
    assert len(build_areas(_devices(), Grouping.ALL)[0].channels) == 10
    per_light = build_areas(_devices(), Grouping.LIGHT)
    assert [a.name for a in per_light] == ["Globe A", "Globe B", "Strip"]
    assert per_light[0].channels[0].position == (0.0, 0.0, 0.0)


def test_client_id_is_stable_and_namespaced():
    assert area_client_id("group-aa", "x") == area_client_id("group-aa", "x")
    assert area_client_id("group-aa", "x") != area_client_id("group-aa", "y")
    assert len(area_client_id("group-aa")) == 16


def test_device_dict_roundtrip():
    device = _devices()[2]
    assert LifxDevice.from_dict(device.to_dict()) == device
