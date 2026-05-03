"""Centralised YAML configuration loader for HAATO-Sim.

Usage anywhere on the main Python side:
    from utility.config_loader import get_config
    cfg = get_config()
    port = cfg["network"]["xplane_port"]
    mission = cfg["missions"][fire_layout]   # fire_layout is an int
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "Copy to X-Plane directory"
    / "Resources"
    / "plugins"
    / "HAATO_assets"
    / "config.yaml"
)

_cache: dict[str, Any] | None = None


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and return the parsed YAML config dict.

    Args:
        path: Override the default config path. Useful in tests.
    """
    global _cache
    target = path or _CONFIG_PATH
    with target.open("r", encoding="utf-8") as fh:
        _cache = yaml.safe_load(fh)
    return _cache


def get_config(path: Path | None = None) -> dict[str, Any]:
    """Return the cached config, loading it on first call."""
    global _cache
    if _cache is None:
        load_config(path)
    return _cache  # type: ignore[return-value]
