#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import struct
from dataclasses import dataclass
from pathlib import Path


MAGIC = b"GRAT"
CELL_SIZE = 20

# Ragnarok GAT terrain types. GRF Editor treats 2/3/4/6 as normal terrain
# for navigation purposes. 1 and 5 are impassable.
WALKABLE_TYPES = {0, 2, 3, 4, 6}


@dataclass
class GatMap:
    name: str
    source: str
    version_major: int
    version_minor: int
    width: int
    height: int
    walkable: bytes
    walkable_cells: int
    blocked_cells: int


def find_gat_header(data: bytes) -> int:
    if data[:4] == MAGIC:
        return 0
    # Some very old files have a zero-byte prefix.
    if len(data) >= 5 and data[0] == 0 and data[1:5] == MAGIC:
        return 1
    raise ValueError("Not a GAT file: missing GRAT signature")


def parse_gat(path: Path, source_name: str) -> GatMap:
    data = path.read_bytes()
    base = find_gat_header(data)

    if len(data) < base + 14:
        raise ValueError("GAT header is truncated")

    major = data[base + 4]
    minor = data[base + 5]
    width = struct.unpack_from("<i", data, base + 6)[0]
    height = struct.unpack_from("<i", data, base + 10)[0]

    if width <= 0 or height <= 0 or width > 10000 or height > 10000:
        raise ValueError(f"Invalid dimensions {width}x{height}")

    cell_count = width * height
    start = base + 14
    required = start + cell_count * CELL_SIZE
    if len(data) < required:
        raise ValueError(
            f"Truncated GAT: expected at least {required:,} bytes, got {len(data):,}"
        )

    grid = bytearray(cell_count)
    walkable_cells = 0

    for i in range(cell_count):
        off = start + i * CELL_SIZE + 16
        raw_type = struct.unpack_from("<i", data, off)[0]

        # GAT 1.3 can encode special flags in the high bits. For navigation,
        # any high-bit special/water flag is conservatively treated as blocked.
        has_special_high_bit = raw_type < 0
        terrain_type = raw_type & 0x7FFFFFFF

        is_walkable = (
            not has_special_high_bit
            and terrain_type in WALKABLE_TYPES
        )

        if is_walkable:
            grid[i] = 1
            walkable_cells += 1

    return GatMap(
        name=path.stem.lower(),
        source=source_name,
        version_major=major,
        version_minor=minor,
        width=width,
        height=height,
        walkable=bytes(grid),
        walkable_cells=walkable_cells,
        blocked_cells=cell_count - walkable_cells,
    )


def discover_maps(raw_root: Path, priorities: list[str]) -> dict[str, tuple[Path, str]]:
    """Resolve duplicates using DATA.ini priority: first listed GRF wins."""
    resolved: dict[str, tuple[Path, str]] = {}

    for source in priorities:
        folder = raw_root / source
        if not folder.exists():
            print(f"[WARN] Missing source folder: {folder}")
            continue

        gat_files = sorted(folder.rglob("*.gat"))
        print(f"[SCAN] {source}: {len(gat_files)} GAT files")

        for gat in gat_files:
            name = gat.stem.lower()
            if name not in resolved:
                resolved[name] = (gat, source)

    return resolved


def write_nav_file(out_path: Path, gat: GatMap) -> None:
    """Write a compact gzip file: one JSON header line + raw 0/1 grid bytes."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = {
        "format": "ragnarok-nav-v1",
        "map": gat.name,
        "source": gat.source,
        "gat_version": f"{gat.version_major}.{gat.version_minor}",
        "width": gat.width,
        "height": gat.height,
        "cell_order": "row-major",
        "walkable_value": 1,
        "blocked_value": 0,
    }

    with gzip.open(out_path, "wb", compresslevel=9) as f:
        f.write((json.dumps(header, separators=(",", ":")) + "\n").encode("utf-8"))
        f.write(gat.walkable)


def build(raw_root: Path, output_root: Path, priorities: list[str]) -> int:
    resolved = discover_maps(raw_root, priorities)
    if not resolved:
        raise SystemExit("No .gat files found.")

    nav_dir = output_root / "nav"
    nav_dir.mkdir(parents=True, exist_ok=True)

    manifest_maps = {}
    failures = []

    print(f"[BUILD] Resolved {len(resolved)} unique maps.")

    for index, (name, (path, source)) in enumerate(sorted(resolved.items()), 1):
        try:
            gat = parse_gat(path, source)
            nav_name = f"{name}.nav.gz"
            write_nav_file(nav_dir / nav_name, gat)

            manifest_maps[name] = {
                "source": source,
                "gat_path": path.relative_to(raw_root).as_posix(),
                "nav_file": f"nav/{nav_name}",
                "gat_version": f"{gat.version_major}.{gat.version_minor}",
                "width": gat.width,
                "height": gat.height,
                "cells": gat.width * gat.height,
                "walkable_cells": gat.walkable_cells,
                "blocked_cells": gat.blocked_cells,
            }

            if index % 100 == 0 or index == len(resolved):
                print(f"[BUILD] {index}/{len(resolved)} maps processed")

        except Exception as exc:
            failures.append({"map": name, "path": str(path), "error": str(exc)})
            print(f"[ERROR] {name}: {exc}")

    manifest = {
        "format": "ragnarok-world-db-v1",
        "grf_priority": priorities,
        "map_count": len(manifest_maps),
        "failed_count": len(failures),
        "maps": manifest_maps,
        "failures": failures,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "maps.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print(f"[DONE] Built {len(manifest_maps)} navigation maps.")
    print(f"[DONE] Failures: {len(failures)}")
    print(f"[DONE] Database: {output_root.resolve()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build compact Ragnarok navigation grids from extracted GAT files."
    )
    parser.add_argument(
        "--raw",
        default="Ragnarok World",
        help="Folder containing 0_hat, 1_soulbound and 2_main.",
    )
    parser.add_argument(
        "--output",
        default="processed",
        help="Output folder for maps.json and nav/*.nav.gz.",
    )
    args = parser.parse_args()

    # DATA.ini:
    # 0=hat.grf
    # 1=soulbound.grf
    # 2=main.grf
    priorities = ["0_hat", "1_soulbound", "2_main"]

    return build(Path(args.raw), Path(args.output), priorities)


if __name__ == "__main__":
    raise SystemExit(main())
