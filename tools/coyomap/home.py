"""Where this coyomap clone keeps its method — one answer for every module that reads it.

`contract` reads its templates from here and `buildstate` reads `method.md` from here. Each kept its
own copy of these three lines until `buildstate` needed them too, and importing `contract` for them
would have made an import cycle: `contract` writes build-state events, so it imports `buildstate`.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    """Where the method and its templates live. `COYOMAP_HOME` wins, because that is the name every
    command in the method already uses; otherwise the installed package's own clone."""
    env = os.environ.get("COYOMAP_HOME", "").strip()
    return Path(env).expanduser().resolve() if env else Path(__file__).resolve().parent.parent.parent
