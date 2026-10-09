"""
Make the provider importable inside an installed Music Assistant server.

These tests only run when the ``music_assistant`` server package is installed (it is not
on PyPI, so plain CI skips them); the provider is mounted as
``music_assistant.providers.lifx_entertainment`` straight from this repository.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

if importlib.util.find_spec("music_assistant") is None:
    collect_ignore_glob = ["test_*.py"]
else:
    if sys.platform == "win32":
        # The server imports the Unix-only ``resource`` module at import time.
        resource = types.ModuleType("resource")
        resource.RLIMIT_NOFILE = 7  # type: ignore[attr-defined]
        resource.getrlimit = lambda _key: (1024, 4096)  # type: ignore[attr-defined]
        resource.setrlimit = lambda _key, _value: None  # type: ignore[attr-defined]
        sys.modules.setdefault("resource", resource)

    import music_assistant.providers

    _PROVIDERS = str(Path(__file__).parents[2] / "music_assistant_provider")
    # Prefer the repository copy over one installed by scripts/install_ma_addon.sh.
    music_assistant.providers.__path__.insert(0, _PROVIDERS)
    for name in [m for m in sys.modules if m.startswith("music_assistant.providers.lifx_")]:
        del sys.modules[name]
