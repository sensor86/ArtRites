# LAST RITES CLF FILE FORMAT — DEFINITIVE REFERENCE
## Based on MISS13.CLF (33768 bytes, 30 zones)
## All structures verified against LR_Exe_disassembly.txt sub_508D4 (lines 65707-65823)

---

## 0. FILE HEADER — sub_51258 (line 66176)

| Offset | Size | Type | Content | MISS13 value |
|--------|------|------|---------|-------------|
| 0x00 | 32 | char[32] | magic "Ocean Compiled Level File V1.00\\0" | — |
| 0x20 | 2 | uint16 LE | dword_E5238 (n_zones) | 30 |
| 0x22 | 2 | uint16 LE | dword_E5290 | 669 |
| 0x24 | 2 | uint16 LE | dword_E5298 | 503 |
| 0x26 | 2 | uint16 LE | dword_E52A0 | 198 |
| 0x28 | 2 | uint16 LE | dword_E529C | 30 |

After header: stream pointer = 0x2A. Zone data begins.

---

## 1. ZONE — sub_508D4 (line 65708), called once per zone

### 1.1 Zone Header — 18 bytes (line 65727)

| Off | Sz | Type | Content |
|-----|-----|------|---------|
| +0 | 4 | int32 LE | hx — world X tile origin |
| +4 | 4 | int32 LE | hy — world Y (vertical axis) |
| +8 | 4 | int32 LE | hz — world Z tile origin |
| +12 | 2 | uint16 LE | flags |
| +14 | 2 | uint16 LE | unknown |
| +16 | 2 | uint16 LE | zone_index (sequential) |

World: wx=-(hx+lx), wy=hy+ly, wz=hz+lz
Grid spacing: 8000 units (80m)

### 1.2 Local Vertex Pool (lines 65729-65738)

| Off | Sz | Type | Content |
|-----|-----|------|---------|
| +0 | 2 | uint16 LE | lvc — local vertex count |
| +2 | 2 | — | padding (stream += 4 total) |
| +4 | lvc×6 | int16×3 | (lx, ly, lz) per vertex, LOCAL coords |

### 1.3 Portal List (lines 65739-65767)

| Off | Sz | Type | Content |
|-----|-----|------|---------|
| +0 | 2 | uint16 LE | raw_pc |
| | | | pc = high_byte if high_byte≠0 else (raw_pc & 0x1FF) |

Portal (per entry, from sub_508D4 lines 65742-65766):
- Skip 6 bytes, read 1 byte flag
- If flag ≠ 1: 7 bytes total
- If flag == 1: 19 bytes + v5×2 extra (where v5 = uint16 at entry+17)

### 1.4 E523C Block (lines 65768-65787)

| Off | Sz | Type | Content |
|-----|-----|------|---------|
| +0 | 2 | uint16 LE | raw → dword_E523C |
| if >0: +2 | 2 | — | padding |
| if >0: +4 | raw×2 | uint16[] | array A |
| if >0: +4+raw×2 | raw×4 | uint32[] | array B |

Total: 2 + (raw>0 ? 2+raw×2+raw×4 : 0) bytes

### 1.5 Polygon List (lines 65788-65790) — sub_505E4 per polygon

| Off | Sz | Content |
|-----|-----|---------|
| +0 | 2 | uint16 n_polys |

**Polygon record (sub_505E4 lines 65537-65579, sub_4EE74 lines 64470-64646):**

| Off | Sz | Content | sub_505E4 action |
|-----|-----|---------|-----------------|
| +0 | 1 | vcnt (3 or 4) | read, advance 1 |
| +1 | vcnt×2 | vertex indices (uint16 LE) | skip vcnt×2 |
| +(1+vcnt×2) | 4 | v2 flags (uint32 LE) | read |
| +(5+vcnt×2) | 3 | color bytes / padding | skip 3 |
| if v2&4: +(8+vcnt×2) | 2 | table_index (uint16) | skip 6 |
| if v2&4: +2 | 1 | byte2 (always 0) | |
| if v2&4: +3 | 1 | byte3 (varies) | |
| if v2&4: +4 | 1 | byte4 flag (0 or 1) | |
| if v2&4: +5 | 1 | byte5 (always 0) | |
| if v2&4: +6 | vcnt×4 | UV: (ux,uy) uint16 pairs | skip vcnt×4 |
| then | vcnt×E523C | lightmap: 1 byte/vert | skip vcnt×E523C |
| then | to align | align dword_E527C to 4 | — |

**Texture data read by sub_4EE74 (polygon init):**
- table_index → indexes width_mask table
- byte2-5 → stored in polygon node (byte4 at v0+9)
- UV pairs → stored at polygon node offsets 38+ and 46+
- See Section 3 for full texture mapping chain

**sub_505E4 byte skip total (v2&4=true, E523C=1):**
  vcnt=4: 1+8+7+6+16+4 = 42 bytes
  vcnt=3: 1+6+7+6+12+3 = 35 bytes

### 1.6 v11 Block (lines 65791-65811)

| Off | Sz | Content |
|-----|-----|---------|
| +0 | 2 | uint16 v11 — count |

Per iteration (sub_4D38C + sub_4D3A0 + sub_4D3FC):
| Sz | Content |
|-----|---------|
| 1 | uint8 v12 — sub-count (sub_4D38C) |
| v12×2 | uint16 array (sub_4D3A0 × v12) |
| 2 | uint16 (sub_4D3A0) |
| 1 | byte (sub_4D3FC) |

Total per iter: 4 + v12×2 bytes

### 1.7 BSP Tree (line 65812) — sub_50528

| Off | Sz | Content |
|-----|-----|---------|
| +0 | 2 | uint16 result |
| if result==0: +2 | 2 | terminal (4 bytes total) |
| if result>0: +2 | result×6+2 | child nodes |

Return value DISCARDED by sub_508D4.

### 1.8 v14 Sub-Zones (lines 65813-65818) — sub_50790 each

| Off | Sz | Content |
|-----|-----|---------|
| +0 | 2 | uint16 v14 — count |

**sub_50790 (line 65648) per sub-zone:**

| Off | Sz | Content |
|-----|-----|---------|
| +0 | 20 | header (skip) |
| +20 | 2 | uint16 count_a |
| +22 | count_a×6 | data |
| then | 2 | uint16 count_b |
| then | portals | count_b portals (same as 1.3) |
| then | 2 | uint16 count_c |
| then | polygons | count_c polygons (sub_506E4 skip: vcnt+indices+flags+texture+lightmap) |
| then | var | BSP tree (sub_50528) |

### 1.9 Tail Data (lines 65819-65822)

| Off | Sz | Content |
|-----|-----|---------|
| +0 | 2 | uint16 result — count |
| +2 | result×20 | tail records |

sub_508D4 returns `result` (the tail count).

---

## 2. POST-ZONE DATA — after all zones in sub_51258

After zone loop (sub_51258 lines 66213-66222):
```
sub_50B30();   sub_63137();
sub_50C00();   sub_63137();
sub_50DC4();   sub_63137();
sub_511DC();   sub_63137();
```

### 2.1 sub_50B30 — entity/object data
Reads: [uint16 count] then count entries of [uint32 type + type-specific skip]

### 2.2 sub_50C00 (line 65877)
Reads: [uint16 count] → dword_E52C4
Each entry: [uint32 type + 8 bytes] then type-specific skip (types 1-14)

### 2.3 sub_50DC4 (line 65963)
Sprite/entity processor with 23 type cases. Returns 1.

### 2.4 sub_511DC (line 66153)
Final cleanup: skips remaining vertex index arrays.

### 2.5 sub_4FD28 (line 65274) — NOT called from sub_51258
Processes polygon texture data (width mask table, E523C, polygon init via sub_4EE74).
Indirect invocation or rendering-time setup. Contains:
- [uint16 count] width mask table entries
- Each: [uint16 raw_tex] [uint16 w_lo_byte] [uint16 w_hi_byte] (6 bytes stream / 4 bytes runtime)
- [uint16 E523C]
- Polygon data via sub_4EE74

---

## 3. LIF TEXTURE LINKAGE

### LIF File Layout
```
0x50000: Palette (768 bytes, 256×3 RGB)
0x50300: uint32 directory_count = dword_E50CC (62 for MISS06/MISS13)
0x50304: Directory entries (count × 12 bytes: {v0, v1, v2})
         v0 → descriptor table offset
0x5070C: Atlas pixel data (256 pixels wide, variable height)
```

### Descriptor Table (at directory[0].v0)
```
[uint32 count]
[uint32 ptr_0]  → detail record  (4 bytes per entry, NOT 8)
[uint32 ptr_1]  → detail record
...
```

### Detail Record (at ptr[i])
```
[uint32 dword0]         — not relocated by sub_4BE58
[uint32 pixel_offset]   — LIF file offset to texture in atlas
[uint32 secondary_ptr]  — relocated by sub_4BE58
```

### Full Texture Mapping Chain

```
POLYGON (CLF):
  uint16 table_index  (in polygon record, read by sub_4D3A0 in sub_4EE74 line 64544)

WIDTH MASK TABLE (runtime, built by sub_4F39C from CLF stream):
  entry[table_index] = { uint16 width_mask, uint16 raw_tex }
  descriptor_tex_id = raw_tex + dword_E50CC   (sub_4F39C line 64765)

DESCRIPTOR LOOKUP (sub_4BE58 line 61443):
  dword_E3050[descriptor_tex_id] = relocated ptr[i]

PIXEL OFFSET (sub_52EA4 line 67720):
  pixel_offset = *(dword_E3050[descriptor_tex_id] + 4)

ATLAS SAMPLE (sub_52EA4):
  byte = atlas_base[pixel_offset + ((coord & width_mask) << 8) + col]
  Column-major layout: byte = pixel_off + row×256 + col
```

### Key Constants
- dword_E50CC: 62 (LIF+0x50300, directory entry count)
- Atlas base: 0x5070C (LIF file offset)
- Atlas width: 256 pixels (fixed)
- Width mask: low byte of table entry's first uint16

---

## 4. FUNCTION INDEX (LR_Exe_disassembly.txt)

| Function | Line | Purpose |
|----------|------|---------|
| sub_51258 | 66176 | CLF loader — entry point, calls zone loop |
| sub_508D4 | 65708 | Zone walk — reads all 9 zone sections |
| sub_505E4 | 65537 | Polygon skip (zone walk, aligns dword_E527C) |
| sub_506E4 | 65600 | Polygon skip (sub_50790, no alignment) |
| sub_50790 | 65648 | Sub-zone processor (called per v14 entry) |
| sub_50528 | — | BSP tree recursive parser |
| sub_4EE74 | 64470 | Polygon init — reads texture/UV from stream |
| sub_4FD28 | 65274 | Post-zone polygon setup (indirect caller) |
| sub_4F39C | 64748 | Width mask table entry builder |
| sub_4D3A0 | 62807 | uint16 stream reader (ignores arguments) |
| sub_4D38C | — | uint8 stream reader |
| sub_4D3FC | — | uint8 stream reader |
| sub_4BE58 | 61443 | Descriptor table relocator → dword_E3050 |
| sub_52EA4 | 67617 | Texture sampler → atlas byte access |
| sub_5AC50 | 74756 | Color conversion (3 bytes → shade) |
| sub_50B30 | — | Post-zone entity processor |
| sub_50C00 | 65877 | Post-zone entity processor |
| sub_50DC4 | 65963 | Post-zone sprite processor (23 types) |
| sub_511DC | 66153 | Post-zone cleanup |
| sub_63137 | 81330 | Event/sync callback dispatcher |

---

## 5. OPEN ISSUES (remaining)

1. **UV divisor**: Raw UV values 0-512 (avg 64). Currently /4. Correct scaling TBD.

2. **byte4 flag (0/1)**: Polygons with byte4=1 have larger UV values (256-512) vs byte4=0 (0-256). May change UV interpretation mode.

3. **Width mask table location in CLF**: Not found in post-zone data. Built by sub_4F39C→sub_4FD28 which has no visible callers in decompilation.

4. **sub_4FD28 invocation**: Function exists (line 65274) but never called in visible decompilation. Likely indirect call or invoked during rendering phase.

5. **byte3 (0/16/64/128/192)**: Varies per polygon, not a UV offset. Purpose unknown.

6. **byte2 (always 0)**: Padding or reserved.
