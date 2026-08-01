# Last Rites (1997) — Technical Reference
## Interim findings for automap & Unity reimplementation
### Session 49 — May 20, 2026

---

## 1. CLF Level File Format

### Header (32 bytes)
```
0x00  Magic: "Ocean Compiled Level File V1.00\0"
```

### Level Info (at 0x20)
```
0x20  u16  n_zones
0x3C  u16  GEO_LIMIT — global vertex pool count
```

### Global Vertex Pool (at 0x40)
```
GEO_LIMIT * 6 bytes — 3 * int16 LE per vertex (lx, ly, lz)
Local tile coords for zone 0.
```

### Zone Walk (start at 0x2A)
```
Zone header (18 bytes):
  +0   int32 hx — world X tile origin
  +4   int32 hy — world Y tile origin
  +8   int32 hz — world Z tile origin
  +12  u16   flags
  +14  u16   ?
  +16  u16   zone_index

Pool vertices: u16 lvc, 4 bytes pad, lvc*6 bytes (3*int16 LE each)

Portals: u16 raw_pc
  pc = high_byte(raw_pc) if high_byte!=0 else (raw_pc & 0x1FF)
  Each: 7 bytes (flag!=1) or 19+v5*2 bytes (flag==1)

E523C block: u16 e523c
  If >0: 2 + e523c*2 + e523c*4 bytes

Polygons: u16 n_polys
  Each:
    byte[0]    vcnt (3 or 4)
    byte[1..]  vertex indices (vcnt * u16 LE)
    u32 v2 + 3 bytes pad
    if v2 & 4: u16 tex_id, byte4, padding, vcnt*(u16 u, u16 v) UVs
    vcnt * E523C bytes

v11 block: u16 v11
  Each: byte v12, then v12*u16 + 1*u16 terminator

sub_50528: recursive BSP, terminal=4 bytes

v14 block: u16 v14
  Each: 20 bytes + portals + polygons + sub_50528

result block: u16 result, result*20 bytes
```

### World-Space Transform
```
world_x = -(hx + lx)
world_y = hy + ly
world_z = hz + lz
```
Face winding: reverse index order for Blender/Unity (CCW front faces).

### Level Stats
| Level  | Zones | Verts | Faces | Entities |
|--------|-------|-------|-------|----------|
| MISS01 | 237   | 14776 | 10770 | 258      |
| MISS04 | 100   | 7415  | 5193  | 104      |
| MISS06 | 311   | 20826 | 15262 | 337      |
| MISS07 | 542   | 8755  | 8297  | 49       |
| MISS08 | 271   | 6100  | 6812  | 755      |
| MISS13 | 30    | —     | 268   | —        |

---

## 2. LIF Texture Atlas

### Layout
```
0x00000  66 bytes 0x2A padding
0x50000  768 bytes palette (256 * RGB)
0x5070C  Atlas pixels (256 wide, ~4400 rows, 8-bit indices)
```

### Descriptor Tables
| Level  | DESC_TABLE | Count |
|--------|------------|-------|
| MISS01 | 0x39A210   | 260   |
| MISS04 | 0x33C010   | 200   |
| MISS13 | 0x2DF910   | 300   |

Format: array of u32 pointers → 32-byte descriptor structs.
All share ATLAS_BASE=0x5070C, palette at 0x50000.

### Descriptor Struct (32 bytes)
```
u32[0] = 0 (validation)
u32[1] = pix (atlas pixel offset)
u32[2..5] = mip/aux pointers + encoded dimensions
u32[6] = mask pointer or dimension data
u32[7] = often same as u32[6]
```

Atlas position: row = (pix - 0x5070C) / 256, col = (pix - 0x5070C) % 256

### Dimension Encoding (3 methods)
Method 1: u32[6] → byte[0]=w_shift, byte[1]=h_shift (valid if both <8)
Method 2: u32[j].b0=w_shift, u32[j].b1=h_shift
Method 3: u32[j].b2=w_shift, u32[k].b2=h_shift (j!=k)

width = 1 << shift

Coverage: MISS13 72/300, MISS01 53/260, MISS04 49/200.
Unknowns: .b2 values 12-30 (complex textures).

### Palette Extraction
```python
for i in range(256):
    r = lif[0x50000 + i*3] * 4
    g = lif[0x50000 + i*3 + 1] * 4
    b = lif[0x50000 + i*3 + 2] * 4
```

---

## 3. UV Coordinates

Polygon UVs (when v2 & 4 set):
```
u16 tex_id, byte4 flags, then vcnt * (u16 u, u16 v)
```

UV scaling (byte4-dependent):
```
byte4=0: 12-bit range (4096) → local_u = (raw_u * width) >> 12
byte4=1: 11-bit range (2048) → local_u = (raw_u * width) >> 11
```

Atlas output:
```
atlas_u = col + clamp(local_u, 0, w-1)
atlas_v = row + (h-1) - clamp(local_v, 0, h-1)
norm_u = atlas_u / 256
norm_v = 1.0 - atlas_v / atlas_height
```

---

## 4. Entities (Game Logic)

Post-zone section after zone loop:
```
u16 count, 2B pad
int32[3] bbox_center
u16 sh_flags, u16 sh_n
sh_n * 14B global params

Entity (18B + subs):
  u16 type (0=enemy, 1-4=portal, 5-17=door/mech, 18-21=trigger, 22-29=pickup)
  u32 x, y, z (sign-extended from u16 pairs)
  u16 flags, u16 n_subs
  n_subs * 14B sub-records
```

Entities are game logic objects, NOT visible props. Street lights etc. are textured geometry.

---

## 5. Key Unsolved

- **tex_id → descriptor mapping**: runtime dword_E3050 array, built by sub_4BE58 from CLF post-zone. Current workaround: manual group_mappings.json
- **84 MISS01 + 47 MISS04 descriptor dimensions**: .b2 values >8 encoding
- **Portal connectivity graph**: needed for automap

---

## 6. Reference Scripts

| Script | Purpose |
|--------|---------|
| export_obj_transformed.py | World-space OBJ (no textures) |
| export_entities.py | Geometry + entity markers |
| session_49/export_v10.py | Textured OBJ with UV scaling |
| session_47/group_mappings.json | Manual tex_id→desc mappings |
| session_49/miss*_catalog.json | Descriptor catalogs |
