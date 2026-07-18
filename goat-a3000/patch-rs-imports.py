#!/usr/bin/env python3
"""
Patch deebot_client Rust extension imports for aarch64 compatibility.

The community ecovacs custom integration ships a Rust extension
(rs.cpython-314-x86_64-linux-musl.so) compiled only for x86_64.
This script wraps each import with try/except ImportError so the
integration loads on a Raspberry Pi (aarch64) without the .so.

Map features (rotation, position overlays, decompression) degrade
gracefully; mowing control and state are unaffected.

Run on the Raspberry Pi:
    python3 /home/admin/goat-a3000/patch-rs-imports.py

Safe to re-run — skips files already patched.
"""

import re
import sys
from pathlib import Path

VENDOR = Path("/home/admin/homeassistant/custom_components/ecovacs/vendor/deebot_client")

# ── fallback bodies ────────────────────────────────────────────────────────────

ROTATION_ANGLE_FALLBACK = """\
try:
    from deebot_client.rs.map import RotationAngle
except ImportError:
    class RotationAngle:  # type: ignore[no-redef]
        \"\"\"Pure-Python stub — Rust extension unavailable on aarch64.\"\"\"
        def __init__(self, value: int = 0) -> None:
            self._value = int(value)
        @classmethod
        def from_int(cls, value: int) -> "RotationAngle":
            return cls(value)
        def __int__(self) -> int:
            return self._value
        def __eq__(self, other: object) -> bool:
            if isinstance(other, RotationAngle):
                return self._value == other._value
            return NotImplemented
        def __repr__(self) -> str:
            return f"RotationAngle({self._value})"
"""

POSITION_TYPE_FALLBACK = """\
try:
    from deebot_client.rs.map import PositionType
except ImportError:
    import enum
    class PositionType(str, enum.Enum):  # type: ignore[no-redef]
        \"\"\"Pure-Python stub — Rust extension unavailable on aarch64.\"\"\"
        DEEBOT = "deebot_pos"
        CHARGER = "chargebase_pos"
"""

ROTATION_AND_POSITION_FALLBACK = """\
try:
    from deebot_client.rs.map import PositionType, RotationAngle
except ImportError:
    import enum
    class PositionType(str, enum.Enum):  # type: ignore[no-redef]
        \"\"\"Pure-Python stub — Rust extension unavailable on aarch64.\"\"\"
        DEEBOT = "deebot_pos"
        CHARGER = "chargebase_pos"
    class RotationAngle:  # type: ignore[no-redef]
        \"\"\"Pure-Python stub — Rust extension unavailable on aarch64.\"\"\"
        def __init__(self, value: int = 0) -> None:
            self._value = int(value)
        @classmethod
        def from_int(cls, value: int) -> "RotationAngle":
            return cls(value)
        def __int__(self) -> int:
            return self._value
        def __eq__(self, other: object) -> bool:
            if isinstance(other, RotationAngle):
                return self._value == other._value
            return NotImplemented
"""

DECOMPRESS_FALLBACK = """\
try:
    from deebot_client.rs.util import decompress_base64_data
except ImportError:
    import base64 as _b64, zlib as _zlib
    def decompress_base64_data(data: str) -> bytes:  # type: ignore[misc]
        \"\"\"Pure-Python fallback — Rust extension unavailable on aarch64.\"\"\"
        raw = _b64.b64decode(data)
        # Try raw deflate first (wbits=-15), then zlib, then gzip.
        for wbits in (-15, 15, 47):
            try:
                return _zlib.decompress(raw, wbits)
            except _zlib.error:
                continue
        return raw  # last resort: return raw bytes
"""

# ── sentinel string that marks a file as already patched ──────────────────────
SENTINEL = "# aarch64-rs-patch-applied"

# ── patch rules: (file_relative_path, original_import_line, replacement) ──────
PATCHES = [
    (
        "messages/json/map/cached_map_info.py",
        r"^from deebot_client\.rs\.map import RotationAngle\s*$",
        ROTATION_ANGLE_FALLBACK,
    ),
    (
        "messages/xml/pos.py",
        r"^from deebot_client\.rs\.map import PositionType\s*$",
        POSITION_TYPE_FALLBACK,
    ),
    (
        "commands/json/map/__init__.py",
        r"^from deebot_client\.rs\.util import decompress_base64_data\s*$",
        DECOMPRESS_FALLBACK,
    ),
    (
        "commands/json/pos.py",
        r"^from deebot_client\.rs\.map import PositionType\s*$",
        POSITION_TYPE_FALLBACK,
    ),
    (
        "commands/xml/map.py",
        r"^from deebot_client\.rs\.map import RotationAngle\s*$",
        ROTATION_ANGLE_FALLBACK,
    ),
    (
        "commands/xml/pos.py",
        r"^from deebot_client\.rs\.map import PositionType\s*$",
        POSITION_TYPE_FALLBACK,
    ),
]

# events/map.py imports inside TYPE_CHECKING — handled separately below
EVENTS_MAP = "events/map.py"
EVENTS_MAP_PATTERN = r"^(\s+)from deebot_client\.rs\.map import PositionType, RotationAngle\s*$"


def patch_file(rel_path: str, pattern: str, replacement: str) -> str:
    """Return 'skipped', 'patched', or 'not_found'."""
    path = VENDOR / rel_path
    if not path.exists():
        return "not_found"

    text = path.read_text()

    if SENTINEL in text:
        return "skipped"

    new_text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count == 0:
        return "skipped"

    # Prepend sentinel comment to the file
    new_text = f"# {SENTINEL}\n" + new_text
    path.write_text(new_text)
    return "patched"


def patch_events_map() -> str:
    """
    events/map.py imports inside a TYPE_CHECKING block — wrap the whole
    block guard so it only imports if the Rust extension is available.
    """
    path = VENDOR / EVENTS_MAP
    if not path.exists():
        return "not_found"

    text = path.read_text()
    if SENTINEL in text:
        return "skipped"

    # Check if the import exists
    if not re.search(EVENTS_MAP_PATTERN, text, re.MULTILINE):
        return "skipped"

    def replacer(m: re.Match) -> str:
        indent = m.group(1)
        return (
            f"{indent}try:\n"
            f"{indent}    from deebot_client.rs.map import PositionType, RotationAngle\n"
            f"{indent}except ImportError:\n"
            f"{indent}    pass  # stubs defined at module level if needed\n"
        )

    new_text = re.sub(EVENTS_MAP_PATTERN, replacer, text, flags=re.MULTILINE)
    new_text = f"# {SENTINEL}\n" + new_text
    path.write_text(new_text)
    return "patched"


def main() -> int:
    if not VENDOR.exists():
        print(f"ERROR: vendor directory not found: {VENDOR}")
        print("Make sure the ecovacs custom integration is installed at")
        print("  /home/admin/homeassistant/custom_components/ecovacs/")
        return 1

    print(f"\nPatching Rust imports in {VENDOR}\n")

    results = {}
    for rel_path, pattern, replacement in PATCHES:
        status = patch_file(rel_path, pattern, replacement)
        results[rel_path] = status
        icon = {"patched": "PATCHED", "skipped": "SKIP   ", "not_found": "MISSING"}[status]
        print(f"  {icon}  {rel_path}")

    status = patch_events_map()
    results[EVENTS_MAP] = status
    icon = {"patched": "PATCHED", "skipped": "SKIP   ", "not_found": "MISSING"}[status]
    print(f"  {icon}  {EVENTS_MAP}")

    missing = [k for k, v in results.items() if v == "not_found"]
    patched = [k for k, v in results.items() if v == "patched"]

    print()
    if missing:
        print(f"WARNING: {len(missing)} file(s) not found — check VENDOR path above.")
    if patched:
        print(f"Applied {len(patched)} patch(es). Restart Home Assistant to pick them up.")
        print("  docker restart home-assistant")
    else:
        print("Nothing to patch — all files already patched or targets not found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
