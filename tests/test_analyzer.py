"""Tests for the provider's audio analyzer, wired to LIFX channels."""

from __future__ import annotations

import importlib.util
import itertools
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

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


@pytest.mark.parametrize("mode", ["smooth", "ambient", "flashing", "energetic", "party"])
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


def _party(analyzer_module, seed=1) -> Any:
    area = _area()
    analyzer = analyzer_module.LifxAudioAnalyzer(area.channels, color_mode="party", seed=seed)
    analyzer.push_beats([_Beat(1_000_000 + i * 500_000, i % 4 == 0) for i in range(40)])
    return analyzer


def _frames(analyzer, start_us, count, step_us=50_000) -> list:
    return [
        [(c.red, c.green, c.blue) for c in analyzer.render(start_us + i * step_us)]
        for i in range(count)
    ]


def test_party_is_reproducible_with_a_seed(analyzer_module):
    first = _frames(_party(analyzer_module, seed=7), 1_000_000, 60)
    second = _frames(_party(analyzer_module, seed=7), 1_000_000, 60)
    assert first == second


def test_party_ignores_album_palette_and_changes_colour(analyzer_module):
    analyzer = _party(analyzer_module)
    analyzer.apply_color_palette({"primary": (255, 0, 0)})
    frames = _frames(analyzer, 1_000_000, 80)
    # More than one distinct colour over a few seconds, and lights differ from each other.
    assert len({frame[0] for frame in frames}) > 3
    assert any(len(set(frame)) > 1 for frame in frames)


def test_party_holds_colour_between_changes(analyzer_module):
    analyzer = _party(analyzer_module)
    # Early in the first beat segment the colour is held (only brightness pulses).
    a = analyzer.render(1_100_000)
    b = analyzer.render(1_150_000)
    hues = [[c.red / max(1, c.red + c.green + c.blue) for c in cmds] for cmds in (a, b)]
    assert hues[0] == pytest.approx(hues[1], abs=0.02)


def test_party_new_track_rotates_hues(analyzer_module):
    analyzer = _party(analyzer_module)
    palette_before = list(analyzer._party_palette())
    analyzer.clear_beat_schedule()
    assert analyzer._party_palette() != palette_before


def test_party_falls_back_to_peaks_without_beats(analyzer_module):
    area = _area()
    analyzer = analyzer_module.LifxAudioAnalyzer(area.channels, color_mode="party", seed=3)
    before = analyzer.render(1_000_000)
    for i in range(3):
        analyzer.apply_peak(255, 1_000_000 + i * 200_000)
    after = [analyzer.render(1_000_000 + t * 50_000) for t in range(1, 40)][-1]
    assert [(c.red, c.green, c.blue) for c in before] != [(c.red, c.green, c.blue) for c in after]


def test_party_fades_gradually(analyzer_module) -> None:
    analyzer = _party(analyzer_module)
    frames = _frames(analyzer, 1_000_000, 80)

    def normalised(rgb: tuple[int, int, int]) -> tuple[float, ...]:
        peak = max(rgb) or 1
        return tuple(v / peak for v in rgb)

    # Ignoring brightness (and the frames on a beat, where the pulse clips towards white),
    # no light jumps colour within one 50 ms frame.
    for index, (before, after) in enumerate(itertools.pairwise(frames)):
        if index % 10 in (9, 0):
            continue
        for first, second in zip(before, after, strict=True):
            step = max(
                abs(a - b) for a, b in zip(normalised(first), normalised(second), strict=True)
            )
            assert step < 0.3
