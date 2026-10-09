"""Tests for the provider's audio analyzer, wired to LIFX channels."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from lifx_entertainment import (
    EntertainmentArea,
    LifxDevice,
    LightColorCommand,
    ZoneSupport,
    build_areas,
)

_ANALYZER = (
    Path(__file__).parent.parent / "music_assistant_provider" / "lifx_entertainment" / "analyzer.py"
)


@pytest.fixture(scope="module")
def analyzer_module() -> ModuleType:
    # Loaded by path: the provider package only imports inside Music Assistant.
    spec = importlib.util.spec_from_file_location("lifx_provider_analyzer", _ANALYZER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class _Beat:
    timestamp_us: int
    is_downbeat: bool


def _area() -> EntertainmentArea:
    devices = [
        LifxDevice("d073d5000001", "1.1.1.1", label="A"),
        LifxDevice("d073d5000002", "1.1.1.2", label="B"),
        LifxDevice(
            "d073d5000003",
            "1.1.1.3",
            label="Strip",
            zone_support=ZoneSupport.EXTENDED,
            zone_count=16,
        ),
    ]
    return build_areas(devices, "all")[0]


@pytest.mark.parametrize("mode", ["smooth", "ambient", "flashing", "energetic"])
def test_render_one_command_per_channel(analyzer_module, mode):
    area = _area()
    analyzer = analyzer_module.LifxAudioAnalyzer(area.channels, color_mode=mode, brightness=80)
    analyzer.apply_color_palette({"primary": (255, 0, 0), "accent": (0, 0, 255)})
    analyzer.push_beats([_Beat(1_000_000 + i * 500_000, i % 4 == 0) for i in range(8)])
    for t in range(40):
        now = 1_000_000 + t * 50_000
        analyzer.apply_spectrum([30000] * 17, now)
        commands = analyzer.render(now)
        assert [c.channel_id for c in commands] == [c.channel_id for c in area.channels]
        assert all(isinstance(c, LightColorCommand) for c in commands)
        assert all(0 <= v <= 65535 for c in commands for v in (c.red, c.green, c.blue))
    assert any(c.red or c.green or c.blue for c in commands)


def test_brightness_zero_is_dark(analyzer_module):
    area = _area()
    analyzer = analyzer_module.LifxAudioAnalyzer(area.channels, brightness=0)
    commands = analyzer.render(1_000_000)
    assert all((c.red, c.green, c.blue) == (0, 0, 0) for c in commands)


def test_palette_uses_full_output(analyzer_module):
    area = _area()
    analyzer = analyzer_module.LifxAudioAnalyzer(area.channels, color_mode="ambient")
    analyzer.apply_color_palette({"primary": (200, 0, 0), "accent": (0, 0, 200)})
    palette = analyzer._active_palette()
    assert max(max(c) for c in palette) == pytest.approx(1.0)
