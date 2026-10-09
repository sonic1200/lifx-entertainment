"""
LIFX Lights Sync Plugin for Music Assistant.

Syncs LIFX lights to music using the Sendspin visualization pipeline and the
LIFX LAN protocol (UDP, no cloud and no bridge).

Each LIFX group (room in the LIFX app) appears as a virtual light player in
Music Assistant. Joining that player to a playing group makes the lights react
to the music in real time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.enums import ProviderFeature
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

SUPPORTED_FEATURES: set[ProviderFeature] = set()


async def setup(
    mass: MusicAssistant,
    manifest: ProviderManifest,
    config: ProviderConfig,
) -> ProviderInstanceType:
    """Initialize provider(instance) with given configuration."""
    from .provider import LifxEntertainmentProvider  # noqa: PLC0415

    # device selection is handled by the setup flow; a provider that somehow lacks
    # devices degrades to unavailable in loaded_in_mass rather than failing here.
    return LifxEntertainmentProvider(mass, manifest, config, SUPPORTED_FEATURES)
