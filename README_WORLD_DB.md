# Ragnarok World Database Builder

This repository contains the extracted map data used by the screen-driven Ragnarok bot.

## GRF priority

The Soulbound client loads:

```ini
[Data]
0=hat.grf
1=soulbound.grf
2=main.grf
```

The builder therefore resolves duplicate map names in this order:

1. `0_hat`
2. `1_soulbound`
3. `2_main`

The first matching map wins, matching the client's override priority.

## Build the navigation database

Run this from the root of the `Ragnarokmap` repository:

```powershell
python tools\build_world_db.py
```

No third-party Python packages are required.

It reads:

```text
Ragnarok World/
├── 0_hat/
├── 1_soulbound/
└── 2_main/
```

and generates:

```text
processed/
├── maps.json
└── nav/
    ├── prontera.nav.gz
    ├── izlude.nav.gz
    ├── iz_dun00.nav.gz
    ├── iz_dun01.nav.gz
    └── ...
```

## What a .nav.gz contains

Each file is gzip-compressed and contains:

1. one UTF-8 JSON header line
2. a row-major byte grid

Each grid byte is:

- `1` = walkable
- `0` = blocked

The header contains the map dimensions and the source GRF.

## Why this exists

The bot should not guess whether a screen coordinate is water or a wall. It can use the real GAT navigation grid to calculate paths through the map, while the visible minimap is used to verify actual movement and position.

The next layer will add:

- A* pathfinding
- current-map identification
- portal/map connections
- NPC/storage destinations
- monster/map information
- item/consumable configuration
- multi-map routes
