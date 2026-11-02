"""Read the installed payload profile once without changing user configuration."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path


_MARKER = Path(__file__).resolve().parents[2] / 'resources' / 'core-install.json'


@lru_cache(maxsize=1)
def is_core_install() -> bool:
    """Only an explicit valid personal-harness payload selects the core profile.

    An absent marker keeps the complete source checkout and legacy payloads
    compatible. The marker is installed code metadata, never a user preference
    or a signal to change existing personal skills, agents or MCP settings.
    """
    try:
        with _MARKER.open('rb') as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return False
        value = json.loads(raw.decode('utf-8-sig'))
        return isinstance(value, dict) and value.get('profile') == 'personal-harness'
    except (OSError, ValueError, UnicodeError):
        return False
