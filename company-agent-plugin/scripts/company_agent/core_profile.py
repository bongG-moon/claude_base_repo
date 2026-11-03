"""Read the installed payload profile once without changing user configuration."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path


_MARKER = Path(__file__).resolve().parents[2] / 'resources' / 'core-install.json'
_FULL_RUNTIME = Path(__file__).resolve().with_name('business.py')


@lru_cache(maxsize=1)
def is_core_install() -> bool:
    """Detect the core profile without changing personal configuration.

    The explicitly marked core wins. If its marker is missing or corrupt, the
    absence of the optional full runtime keeps the incomplete payload in the
    safe core mode. A complete source checkout without a marker remains full.
    """
    try:
        with _MARKER.open('rb') as stream:
            raw = stream.read(4097)
        if len(raw) <= 4096:
            value = json.loads(raw.decode('utf-8-sig'))
            if isinstance(value, dict) and value.get('profile') == 'personal-harness':
                return True
    except (OSError, ValueError, UnicodeError):
        pass
    return not _FULL_RUNTIME.is_file()
