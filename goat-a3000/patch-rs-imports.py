#!/usr/bin/env python3
"""
Patch deebot_client Rust extension imports for aarch64 compatibility.

The community ecovacs custom integration (email-device-auth build) ships a
Rust extension compiled only for x86_64 (rs.cpython-314-x86_64-linux-musl.so).
On a Raspberry Pi (aarch64) every `deebot_client.rs` import fails with
ModuleNotFoundError and the integration cannot load.

This script wraps all nine import sites with try/except ImportError and
provides pure-Python stubs. Map rendering degrades to "no image"; mowing
control, state, zones, and events are unaffected.

Covers:
  - 6 absolute imports  (from deebot_client.rs.map / .rs.util ...)
  - 1 TYPE_CHECKING import (events/map.py)
  - 2 relative imports  (map.py, device.py — from .rs.map ...)

Run on the Raspberry Pi:
    sudo python3 patch-rs-imports.py

Idempotent: files whose import is already wrapped are skipped. After
patching, clear stale bytecode and restart HA:
    sudo find <vendor> -name '*.pyc' -delete
    docker restart home-assistant
"""

import sys
from pathlib import Path

VENDOR = Path("/home/admin/homeassistant/custom_components/ecovacs/vendor/deebot_client")

# ── stub blocks ───────────────────────────────────────────────────────────────

ROTATION_ANGLE_STUB = """\
try:
    from deebot_client.rs.map import RotationAngle
except ImportError:
    from enum import IntEnum as _IntEnum

    class RotationAngle(_IntEnum):  # type: ignore[no-redef]
        DEG_0 = 0
        DEG_90 = 90
        DEG_180 = 180
        DEG_270 = 270

        @classmethod
        def from_int(cls, value):
            try:
                return cls(int(value))
            except ValueError:
                return cls.DEG_0
"""

POSITION_TYPE_STUB = """\
try:
    from deebot_client.rs.map import PositionType
except ImportError:
    import enum

    class PositionType(str, enum.Enum):  # type: ignore[no-redef]
        DEEBOT = "deebot_pos"
        CHARGER = "chargebase_pos"
"""

POSITION_TYPE_RELATIVE_STUB = """\
try:
    from .rs.map import PositionType
except ImportError:
    import enum

    class PositionType(str, enum.Enum):  # type: ignore[no-redef]
        DEEBOT = "deebot_pos"
        CHARGER = "chargebase_pos"
"""

DECOMPRESS_STUB = """\
try:
    from deebot_client.rs.util import decompress_base64_data
except ImportError:
    import base64 as _b64
    import zlib as _zlib

    def decompress_base64_data(data):  # type: ignore[misc]
        raw = _b64.b64decode(data)
        for wbits in (-15, 15, 47):
            try:
                return _zlib.decompress(raw, wbits)
            except _zlib.error:
                continue
        return raw
"""

# map.py needs a functional MapData stub: MapData() is instantiated per device
# and its attributes are hit by live map events from the mower.
MAP_DATA_STUB = """\
try:
    from .rs.map import MapData as MapDataRs, RotationAngle
except ImportError:
    # aarch64: bundled Rust extension is x86_64-only. Pure-Python stubs;
    # map rendering degrades to "no image", mowing control unaffected.
    from enum import IntEnum as _IntEnum

    class RotationAngle(_IntEnum):  # type: ignore[no-redef]
        DEG_0 = 0
        DEG_90 = 90
        DEG_180 = 180
        DEG_270 = 270

        @classmethod
        def from_int(cls, value):
            try:
                return cls(int(value))
            except ValueError:
                return cls.DEG_0

    class _StubTracePoints:
        def add(self, value):
            pass

        def clear(self):
            pass

    class _StubBackgroundImage:
        def update_map_piece(self, index, base64_data):
            return False

        def map_piece_crc32_indicates_update(self, index, crc32):
            return False

    class _StubMapInfo:
        def set(self, base64_info):
            pass

    class MapDataRs:  # type: ignore[no-redef]
        def __init__(self):
            self.trace_points = _StubTracePoints()
            self.background_image = _StubBackgroundImage()
            self.map_info = _StubMapInfo()

        def generate_svg(self, subsets, positions, rotation):
            return None
"""

# events/map.py: import lives in a TYPE_CHECKING block (never executed at
# runtime), so a plain pass fallback is enough.
EVENTS_MAP_OLD = "    from deebot_client.rs.map import PositionType, RotationAngle\n"
EVENTS_MAP_NEW = """\
    try:
        from deebot_client.rs.map import PositionType, RotationAngle
    except ImportError:
        pass
"""

# ── patch table: (relative path, exact original import line, replacement) ────

PATCHES = [
    ("map.py",
     "from .rs.map import MapData as MapDataRs, RotationAngle\n",
     MAP_DATA_STUB),
    ("device.py",
     "from .rs.map import PositionType\n",
     POSITION_TYPE_RELATIVE_STUB),
    ("messages/json/map/cached_map_info.py",
     "from deebot_client.rs.map import RotationAngle\n",
     ROTATION_ANGLE_STUB),
    ("messages/xml/pos.py",
     "from deebot_client.rs.map import PositionType\n",
     POSITION_TYPE_STUB),
    ("commands/json/map/__init__.py",
     "from deebot_client.rs.util import decompress_base64_data\n",
     DECOMPRESS_STUB),
    ("commands/json/pos.py",
     "from deebot_client.rs.map import PositionType\n",
     POSITION_TYPE_STUB),
    ("commands/xml/map.py",
     "from deebot_client.rs.map import RotationAngle\n",
     ROTATION_ANGLE_STUB),
    ("commands/xml/pos.py",
     "from deebot_client.rs.map import PositionType\n",
     POSITION_TYPE_STUB),
    ("events/map.py",
     EVENTS_MAP_OLD,
     EVENTS_MAP_NEW),
]


def patch_file(rel_path, old, new):
    path = VENDOR / rel_path
    if not path.exists():
        return "MISSING"

    text = path.read_text(encoding="utf-8")

    # No pristine deebot_client file contains "except ImportError" — its
    # presence means this file was already patched (by this script or an
    # earlier manual fix, regardless of wrapping style).
    if "except ImportError" in text:
        return "SKIP"

    if old not in text:
        return "SKIP"

    import py_compile
    import tempfile

    patched = text.replace(old, new, 1)

    # Compile-check before touching the real file.
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as tmp:
        tmp.write(patched)
        tmp_path = tmp.name
    try:
        py_compile.compile(tmp_path, doraise=True)
    except py_compile.PyCompileError as err:
        Path(tmp_path).unlink(missing_ok=True)
        print(f"  COMPILE ERROR in {rel_path}: {err}")
        return "ERROR"
    Path(tmp_path).unlink(missing_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(patched)
    return "PATCHED"


def main():
    if not VENDOR.exists():
        print(f"ERROR: vendor directory not found: {VENDOR}")
        return 1

    print(f"\nPatching Rust-extension imports in {VENDOR}\n")

    errors = 0
    patched = 0
    for rel_path, old, new in PATCHES:
        status = patch_file(rel_path, old, new)
        print(f"  {status:8s} {rel_path}")
        if status == "ERROR":
            errors += 1
        elif status == "PATCHED":
            patched += 1

    print()
    if errors:
        print(f"{errors} file(s) failed the compile check — NOT modified.")
        return 1
    if patched:
        print(f"Applied {patched} patch(es). Now clear bytecode and restart HA:")
        print(f"  sudo find {VENDOR.parent} -name '*.pyc' -delete")
        print("  docker restart home-assistant")
    else:
        print("Nothing to do — all files already patched or targets absent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
